"""Bench-controlled execution adapter for the native Claude Code dynamic-workflow
graph candidate (contracts/CONTRACTS.md §9).

Two things live here and must not be confused:

* the **versioned native workflow template** under ``workflow/`` — the script the
  operator would hand to the native runtime, plus a JSON declaration of its nodes,
  dependencies, exclusive file ownership, stable-ID joins, retry policy and final
  artifact contract; and
* the **bench-controlled runner** in this module — ``run()`` — which executes the
  declared graph through an *injected* executor, enforces the limits the bench really
  can enforce, and emits ``trace-event/1`` events.

Nothing in this module talks to a model provider. ``FakeExecutor`` is provider-free by
construction: it scripts deterministic behaviours in-process and the only subprocess it
ever spawns is this interpreter sleeping, so a timeout test has a real child to reap.
``LiveExecutor`` shells out to an *explicitly configured* command and fails closed when
that command is missing or when ``capabilities()['available']`` is false; it has no
fallback path to a raw model API and no endpoint of any kind.

Honest enforcement labels (§6 vocabulary):

===========================  ============  ======================================
limit                        enforcement   how
===========================  ============  ======================================
``max_concurrency``          enforced      bounded dispatch, peak observed
``max_workers``              enforced      surplus worker nodes are skipped
``max_attempts_total``       enforced      global attempt reservation
``max_elapsed_seconds``      enforced      deadline; owned subprocesses reaped
``max_tokens``               unavailable   the runtime exposes no token ceiling
``max_cost_usd``             unavailable   the runtime exposes no cost ceiling
===========================  ============  ======================================

A token or cost limit that is supplied anyway is reported as ``advisory`` and is never
claimed to be enforced. See ``CAPABILITY.md`` for what was and was not verified on this
machine, including the ``/effort ultracode`` confound.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from bench_core import traces
from bench_core.common import canonical, measurement, require

NAME = 'claude_workflow'
VERSION = '1.0.0'
ADAPTER_CONTRACT = 'adapter/1'
WORKFLOW_CONTRACT = 'workflow-definition/1'
IMPORTER = 'claude_workflow_adapter'

HERE = Path(__file__).resolve().parent
WORKFLOW_DIR = HERE / 'workflow'
DEFAULT_WORKFLOW = WORKFLOW_DIR / 'workflow.json'
SOLO_WORKFLOW = WORKFLOW_DIR / 'solo.json'

#: Claude Code version floor at which the bundled ``/workflow-authoring`` reference and
#: the current script API exist (documented; see CAPABILITY.md §1).
MIN_CLI_VERSION = (2, 1, 248)

ENFORCED = 'enforced'
ADVISORY = 'advisory'
UNAVAILABLE = 'unavailable'


class WorkflowDefinitionError(ValueError):
    """The workflow JSON does not satisfy workflow-definition/1."""


class NodeFailure(Exception):
    """An executor reported that a node attempt failed. Retryable."""


class FaultInjected(Exception):
    """A scripted crash fired at a semantic milestone. Aborts the run like a process death."""

    def __init__(self, milestone, node_id, attempt):
        super().__init__(f'fault injected at milestone {milestone!r} '
                         f'(node {node_id!r}, attempt {attempt})')
        self.milestone = milestone
        self.node_id = node_id
        self.attempt = attempt


class LiveExecutorUnavailable(RuntimeError):
    """The live executor refused to run. It never falls back to a raw model API call."""


# --------------------------------------------------------------------------- limits
@dataclass
class Limits:
    """Bench-side limits. Only the first four are actually enforced by ``run()``."""

    max_concurrency: int = 1
    max_workers: int = 1
    max_attempts_total: int = 1
    max_elapsed_seconds: float = 60.0
    max_tokens: int = None
    max_cost_usd: float = None

    @classmethod
    def coerce(cls, value):
        if isinstance(value, cls):
            return value
        require(isinstance(value, dict), 'limits must be a Limits or a dict')
        unknown = set(value) - {f for f in cls.__dataclass_fields__}
        require(not unknown, f'Unknown limit keys: {sorted(unknown)}')
        limits = cls(**value)
        require(limits.max_concurrency >= 1, 'max_concurrency must be >= 1')
        require(limits.max_workers >= 0, 'max_workers must be >= 0')
        require(limits.max_attempts_total >= 1, 'max_attempts_total must be >= 1')
        require(limits.max_elapsed_seconds > 0, 'max_elapsed_seconds must be > 0')
        return limits

    def enforcement(self):
        """The honest enforcement label for every limit, per §6 vocabulary."""
        return {
            'max_concurrency': {'limit': self.max_concurrency, 'enforcement': ENFORCED},
            'max_workers': {'limit': self.max_workers, 'enforcement': ENFORCED},
            'max_attempts_total': {'limit': self.max_attempts_total, 'enforcement': ENFORCED},
            'max_elapsed_seconds': {'limit': self.max_elapsed_seconds, 'enforcement': ENFORCED},
            'max_tokens': {'limit': self.max_tokens,
                           'enforcement': ADVISORY if self.max_tokens is not None else UNAVAILABLE},
            'max_cost_usd': {'limit': self.max_cost_usd,
                             'enforcement': ADVISORY if self.max_cost_usd is not None else UNAVAILABLE},
        }


# --------------------------------------------------------------------------- faults
@dataclass
class FaultPlan:
    """A scripted fault keyed by a **semantic milestone string**.

    The same object is accepted by the graph workflow and by the single-node ``solo``
    workflow, so a scenario lane can inject the identical fault into either shape:

    >>> FaultPlan('first_persisted_ack', 'crash')                    # doctest: +SKIP
    >>> FaultPlan('first_persisted_ack', 'fail', node_id='worker-b') # doctest: +SKIP

    ``kind``:
      * ``crash``  — raise :class:`FaultInjected`; the run aborts as a process death would,
        after the recorded state has been flushed, so a restart can resume from it.
      * ``fail``   — raise :class:`NodeFailure`; an ordinary retryable node failure.
      * ``hang``   — block until the run's cancel event is set (exercises the elapsed cap).

    ``node_id``/``attempt`` are optional filters (``None`` matches any). A plan fires
    at most ``times`` times per run.
    """

    milestone: str
    kind: str = 'crash'
    node_id: str = None
    attempt: int = None
    times: int = 1
    _fired: int = field(default=0, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    KINDS = ('crash', 'fail', 'hang')

    def __post_init__(self):
        require(isinstance(self.milestone, str) and self.milestone.strip(),
                'A FaultPlan needs a semantic milestone string')
        require(self.kind in self.KINDS, f'Unknown fault kind: {self.kind!r}')

    def matches(self, milestone, node_id, attempt):
        if milestone != self.milestone:
            return False
        if self.node_id is not None and self.node_id != node_id:
            return False
        if self.attempt is not None and self.attempt != attempt:
            return False
        return True

    def claim(self, milestone, node_id, attempt):
        """Reserve one firing. Returns True at most ``times`` times per plan."""
        with self._lock:
            if self._fired >= self.times or not self.matches(milestone, node_id, attempt):
                return False
            self._fired += 1
            return True

    def reset(self):
        with self._lock:
            self._fired = 0


# --------------------------------------------------------------------------- effects
class EffectsLog:
    """Append-only, keyed log of externally visible effects.

    A restart replays work; it must not replay an *effect*. Every effect is written
    through :meth:`append_once`, which is keyed and idempotent across processes because
    the key set is re-read from the file, so a duplicated attempt appends nothing.
    """

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def keys(self):
        if not self.path.exists():
            return []
        return [json.loads(line)['key'] for line in self.path.read_text().splitlines() if line.strip()]

    def entries(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def append_once(self, key, value=None):
        """Append ``key`` unless it is already present. Returns True if it was appended."""
        with self._lock:
            if key in set(self.keys()):
                return False
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('a') as handle:
                handle.write(canonical({'key': key, 'value': value}) + '\n')
            return True


# --------------------------------------------------------------------------- state
class RunState:
    """Restart state: what each node produced, so a resume can reuse it *after checks*.

    Reuse is never automatic. :meth:`reusable` requires both the recorded
    ``sourceRevision`` and the recorded ``artifactHash`` to match what the executor
    reports for the node *now*.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.data = {'runId': None, 'attemptsUsed': 0, 'nodes': {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            self.data.setdefault('nodes', {})
            self.data.setdefault('attemptsUsed', 0)
        self._lock = threading.Lock()

    def record(self, node_id, attempt, source_revision, artifact_hash, payload):
        with self._lock:
            self.data['nodes'][node_id] = {
                'attempt': attempt, 'sourceRevision': source_revision,
                'artifactHash': artifact_hash, 'payload': payload, 'status': 'completed'}

    def completed(self, node_id):
        return self.data['nodes'].get(node_id)

    def reusable(self, node_id, source_revision, artifact_hash):
        """Explicit identity check: same source revision *and* same artifact hash."""
        record = self.completed(node_id)
        if not record:
            return False, 'not previously completed'
        if source_revision is None or record.get('sourceRevision') != source_revision:
            return False, (f'source revision changed '
                           f'({record.get("sourceRevision")!r} -> {source_revision!r})')
        if artifact_hash is None or record.get('artifactHash') != artifact_hash:
            return False, (f'artifact hash changed '
                           f'({record.get("artifactHash")!r} -> {artifact_hash!r})')
        return True, 'source revision and artifact hash both match'

    def flush(self, run_id=None, attempts_used=None):
        with self._lock:
            if run_id is not None:
                self.data['runId'] = run_id
            if attempts_used is not None:
                self.data['attemptsUsed'] = attempts_used
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps(self.data, indent=2, sort_keys=True) + '\n')
            temp.replace(self.path)


# --------------------------------------------------------------------------- process registry
class ProcessRegistry:
    """Subprocesses the bench owns, so the elapsed-time cap can stop **and reap** them."""

    def __init__(self):
        self._procs = []
        self._lock = threading.Lock()

    def register(self, proc):
        with self._lock:
            self._procs.append(proc)
        return proc

    def pids(self):
        with self._lock:
            return [p.pid for p in self._procs]

    def reap(self, grace=2.0):
        """Terminate, then kill, then *wait* on every owned subprocess. Returns reaped pids."""
        with self._lock:
            procs = list(self._procs)
        reaped = []
        for proc in procs:
            if proc.poll() is not None:
                proc.wait()
                reaped.append(proc.pid)
                continue
            try:
                proc.terminate()
            except (ProcessLookupError, OSError):
                pass
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except (ProcessLookupError, OSError):
                    pass
                try:
                    proc.wait(timeout=grace)
                except subprocess.TimeoutExpired:
                    continue
            reaped.append(proc.pid)
        return reaped


# --------------------------------------------------------------------------- tasks
@dataclass
class NodeTask:
    """What an executor is handed for one attempt at one node."""

    run_id: str
    node: dict
    attempt: int
    source_revision: str
    workspace: Path
    inputs: dict
    effects: EffectsLog
    processes: ProcessRegistry
    cancel: threading.Event
    args: dict
    _fault: FaultPlan = None
    _on_fault: object = None

    @property
    def node_id(self):
        return self.node['id']

    @property
    def role(self):
        return self.node['role']

    def checkpoint(self, milestone):
        """Semantic milestone hook. Identical for the graph and the solo workflow.

        An executor calls this at named points in its own work (``first_persisted_ack``,
        ``final_artifact_written``, …). When a :class:`FaultPlan` matches, the scripted
        fault fires here and nowhere else, which is what makes restart tests deterministic.
        """
        require(isinstance(milestone, str) and milestone.strip(), 'milestone must be a string')
        plan = self._fault
        if plan is None or not plan.claim(milestone, self.node_id, self.attempt):
            return
        if self._on_fault is not None:
            self._on_fault(milestone, self.node_id, self.attempt, plan.kind)
        if plan.kind == 'crash':
            raise FaultInjected(milestone, self.node_id, self.attempt)
        if plan.kind == 'fail':
            raise NodeFailure(f'scripted failure at milestone {milestone!r}')
        self.cancel.wait()  # kind == 'hang'


# --------------------------------------------------------------------------- executors
class FakeExecutor:
    """Deterministic, provider-free executor. **No network, no model CLI, by construction.**

    Behaviours are scripted per node id:

    ``succeed``                     complete on the first attempt
    ``fail_times:<n>``              fail the first ``n`` attempts, then succeed
    ``fail``                        fail every attempt
    ``hang``                        block until the run's cancel event is set
    ``spawn_child_and_hang``        spawn a *real* sleeping child (this interpreter),
                                    register it with the bench, then block — so the
                                    elapsed-time cap has something to reap
    ``duplicate``                   succeed, and emit the same output twice
    ``stale_verdict``               (reviewer) emit verdicts at the wrong sourceRevision
    ``missing_output``              succeed with no output payload at all

    The only subprocess this class can ever create is ``[sys.executable, '-c', …]``
    sleeping; see :data:`FakeExecutor.CHILD_ARGV_HEAD`. It imports no HTTP client, holds
    no endpoint and consults no credentials.
    """

    SYNTHETIC = True
    CLOCK_SOURCE = 'synthetic'
    #: the complete, hardcoded head of the only argv this executor can spawn
    CHILD_ARGV_HEAD = (sys.executable, '-c')

    def __init__(self, behaviors=None, revisions=None, artifact_hashes=None,
                 milestones=('first_persisted_ack',), step_seconds=0.0, child_seconds=60):
        self.behaviors = dict(behaviors or {})
        self.revisions = dict(revisions or {})
        self.artifact_hashes = dict(artifact_hashes or {})
        self.milestones = tuple(milestones)
        self.step_seconds = step_seconds
        self.child_seconds = child_seconds
        self.attempts = {}
        self.executed = []
        self._lock = threading.Lock()

    # -- identity (cheap, no work done) ----------------------------------
    def identity(self, task):
        """Report the node's current identity without doing its work.

        ``run()`` calls this before reusing a recorded completion, so reuse is gated on
        an explicit source-revision + artifact-hash check rather than on position.
        """
        return {'sourceRevision': self.revisions.get(task.node_id, task.source_revision),
                'artifactHash': self._artifact_hash(task)}

    def _artifact_hash(self, task):
        override = self.artifact_hashes.get(task.node_id)
        if override is not None:
            return override
        seed = f'{task.node_id}|{self.revisions.get(task.node_id, task.source_revision)}'
        return sha256(seed.encode()).hexdigest()

    # -- execution --------------------------------------------------------
    def execute(self, task):
        behavior = self.behaviors.get(task.node_id, 'succeed')
        with self._lock:
            self.attempts[task.node_id] = self.attempts.get(task.node_id, 0) + 1
            seen = self.attempts[task.node_id]
            self.executed.append((task.node_id, task.attempt))

        if behavior == 'spawn_child_and_hang':
            proc = subprocess.Popen([*self.CHILD_ARGV_HEAD,
                                     f'import time; time.sleep({int(self.child_seconds)})'])
            task.processes.register(proc)
            task.cancel.wait()
            raise NodeFailure('canceled while hanging with an owned child process')

        if behavior == 'hang':
            task.cancel.wait()
            raise NodeFailure('canceled while hanging')

        if self.step_seconds:
            # interruptible sleep: the cancel event releases it immediately
            task.cancel.wait(self.step_seconds)

        if behavior == 'fail':
            raise NodeFailure(f'scripted permanent failure for {task.node_id}')
        if behavior.startswith('fail_times:'):
            budget = int(behavior.split(':', 1)[1])
            if seen <= budget:
                raise NodeFailure(f'scripted failure {seen}/{budget} for {task.node_id}')

        revision = self.revisions.get(task.node_id, task.source_revision)
        artifact_hash = self._artifact_hash(task)

        # An externally visible effect, written through the keyed append-only log.
        task.effects.append_once(f'{task.node_id}:persisted',
                                 {'sourceRevision': revision, 'artifactHash': artifact_hash})
        for milestone in self.milestones:
            task.checkpoint(milestone)

        if behavior == 'missing_output':
            return {'nodeId': task.node_id, 'sourceRevision': revision,
                    'artifactHash': artifact_hash, 'outputs': [], 'usage': self._usage()}

        if task.role == 'reviewer':
            targets = sorted(task.inputs.get('workerOutputs', {}))
            verdict_revision = 'stale-revision' if behavior == 'stale_verdict' else None
            outputs = [{'stableId': f'verdict:{target}', 'targetNodeId': target,
                        'sourceRevision': verdict_revision
                        or task.inputs['workerOutputs'][target].get('sourceRevision'),
                        'verdict': 'approve', 'reason': 'synthetic fixture verdict'}
                       for target in targets]
        else:
            outputs = [{'stableId': task.node_id, 'nodeId': task.node_id,
                        'sourceRevision': revision, 'artifactHash': artifact_hash,
                        'summary': f'synthetic output for {task.node_id}'}]
            if behavior == 'duplicate':
                outputs = outputs + [dict(outputs[0])]

        return {'nodeId': task.node_id, 'sourceRevision': revision,
                'artifactHash': artifact_hash, 'outputs': outputs, 'usage': self._usage()}

    def _usage(self):
        return {'inputTokens': None, 'outputTokens': None, 'costUSD': None}

    # -- provenance -------------------------------------------------------
    def describe(self):
        return {'executor': 'FakeExecutor', 'provider': None, 'paidCallsMade': False,
                'model': {'requested': None, 'effective': None, 'verified': False},
                'settings': {'requested': {}, 'effective': None, 'verified': False}}


class LiveExecutor:
    """Executor for a real native workflow run. **Never executed by this lane.**

    It refuses unless *both* hold:

    1. an explicit ``run_command`` was configured (from the method JSON or the caller) —
       there is no default and no guess; and
    2. ``capabilities()['available']`` is true and every required capability check passed.

    There is no fallback: a refusal raises :class:`LiveExecutorUnavailable` and the run
    fails closed. This class contains no provider endpoint, no SDK import and no
    credential lookup; it can only invoke the exact command it was handed.
    """

    SYNTHETIC = False
    CLOCK_SOURCE = 'bench'

    def __init__(self, run_command=None, capabilities_fn=None, requested_model=None,
                 requested_settings=None, timeout_seconds=None):
        self.run_command = list(run_command) if run_command else None
        self._capabilities = capabilities_fn or capabilities
        self.requested_model = requested_model
        self.requested_settings = dict(requested_settings or {})
        self.timeout_seconds = timeout_seconds
        #: stays null/unverified until a real run is observed (contract §3)
        self.effective_model = None
        self.effective_settings = None
        self.effective_verified = False

    def preflight(self):
        """Raise unless a run command is configured *and* capabilities are available."""
        if not self.run_command:
            raise LiveExecutorUnavailable(
                'LiveExecutor requires an explicitly configured run command '
                '(methods/graph.json -> adapter_workflow.live.run_command). '
                'There is no default and no fallback to a raw model API.')
        report = self._capabilities()
        if not report.get('available'):
            failed = [c['name'] for c in report.get('checked', []) if not c.get('ok')]
            raise LiveExecutorUnavailable(
                'Native workflow capabilities are unavailable, so the live executor fails '
                f'closed. Failed checks: {failed or ["unknown"]}. '
                'It never falls back to raw model API calls.')
        return report

    def identity(self, task):
        # Offline we cannot know a live node's artifact hash; unknown stays unknown.
        return {'sourceRevision': task.source_revision, 'artifactHash': None}

    def execute(self, task):
        self.preflight()
        raise LiveExecutorUnavailable(
            'Live execution is a paid model call and is not performed by the workflow lane. '
            'Configure and launch it deliberately as the operator.')

    def describe(self):
        return {'executor': 'LiveExecutor',
                'runCommand': self.run_command,
                'paidCallsMade': False,
                'model': {'requested': self.requested_model,
                          'effective': self.effective_model,
                          'verified': self.effective_verified},
                'settings': {'requested': self.requested_settings,
                             'effective': self.effective_settings,
                             'verified': self.effective_verified}}


# --------------------------------------------------------------------------- capabilities
def _cli_version(binary):
    out = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=30)
    text = (out.stdout or out.stderr or '').strip()
    parts = text.split()
    numbers = parts[0].split('.') if parts else []
    try:
        return text, tuple(int(n) for n in numbers[:3])
    except ValueError:
        return text, None


def _workflows_disabled():
    """Read the documented off-switches without executing anything."""
    reasons = []
    if os.environ.get('CLAUDE_CODE_DISABLE_WORKFLOWS'):
        reasons.append('CLAUDE_CODE_DISABLE_WORKFLOWS is set')
    config_dir = Path(os.environ.get('CLAUDE_CONFIG_DIR') or (Path.home() / '.claude'))
    settings = config_dir / 'settings.json'
    if settings.is_file():
        try:
            if json.loads(settings.read_text()).get('disableWorkflows') is True:
                reasons.append(f'{settings} sets disableWorkflows')
        except (OSError, json.JSONDecodeError) as error:
            reasons.append(f'{settings} unreadable ({error})')
    managed = Path('/Library/Application Support/ClaudeCode/managed-settings.json')
    if managed.is_file():
        try:
            if json.loads(managed.read_text()).get('disableWorkflows') is True:
                reasons.append('managed settings disable workflows')
        except (OSError, json.JSONDecodeError):
            reasons.append('managed settings unreadable')
    return reasons


def _headless_permission_rule():
    config_dir = Path(os.environ.get('CLAUDE_CONFIG_DIR') or (Path.home() / '.claude'))
    settings = config_dir / 'settings.json'
    if not settings.is_file():
        return []
    try:
        allow = json.loads(settings.read_text()).get('permissions', {}).get('allow', [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return []
    return [rule for rule in allow if isinstance(rule, str) and rule.split('(')[0].strip() == 'Workflow']


def capabilities(workflow_path=DEFAULT_WORKFLOW):
    """Inspection only. **Never invokes a model** and always reports ``paidCallsMade: false``.

    Every check is a version read, a settings read or a file listing. ``claude --version``
    is the only subprocess, and no prompt is ever passed.
    """
    checked = []

    binary = shutil.which('claude')
    checked.append({'name': 'claude_on_path', 'ok': bool(binary),
                    'detail': binary or 'no `claude` executable on PATH'})

    version_text, version = (None, None)
    if binary:
        try:
            version_text, version = _cli_version(binary)
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired) as error:
            version_text = f'version probe failed: {error}'
    checked.append({'name': 'cli_version_floor', 'ok': bool(version and version >= MIN_CLI_VERSION),
                    'detail': f'{version_text} (floor '
                              f'{".".join(str(n) for n in MIN_CLI_VERSION)})'})

    disabled = _workflows_disabled()
    checked.append({'name': 'workflows_not_disabled', 'ok': not disabled,
                    'detail': '; '.join(disabled) if disabled
                              else 'no disableWorkflows setting and no off-switch env var'})

    try:
        definition = load_workflow(workflow_path)
        detail = f'{definition["id"]} v{definition["version"]} ({definition["scriptVersion"]})'
        ok = True
    except (WorkflowDefinitionError, OSError, json.JSONDecodeError) as error:
        detail, ok = str(error), False
    checked.append({'name': 'workflow_definition', 'ok': ok, 'detail': detail})

    script = WORKFLOW_DIR / 'graph-candidate.v1.js'
    checked.append({'name': 'workflow_script_present', 'ok': script.is_file(),
                    'detail': str(script.relative_to(HERE.parent.parent))
                              if script.is_file() else f'missing {script}'})

    config_dir = Path(os.environ.get('CLAUDE_CONFIG_DIR') or (Path.home() / '.claude'))
    saved = sorted((config_dir / 'workflows').glob('*.js')) if (config_dir / 'workflows').is_dir() else []
    checked.append({'name': 'saved_workflow_installed', 'ok': bool(saved),
                    'detail': ', '.join(p.name for p in saved)
                              or f'no saved workflows under {config_dir / "workflows"}; '
                                 'the versioned script here has not been installed as a command'})

    rules = _headless_permission_rule()
    checked.append({'name': 'headless_permission_rule', 'ok': bool(rules),
                    'detail': ', '.join(rules)
                              or 'no `Workflow` allow rule; a headless launch would depend on '
                                 'auto mode or a hook. The ultracode keyword is not a headless opt-in.'})

    return {
        'contract': ADAPTER_CONTRACT,
        'adapter': NAME,
        'adapterVersion': VERSION,
        'available': all(check['ok'] for check in checked),
        'checked': checked,
        'paidCallsMade': False,
        'inspectionOnly': True,
        'notes': 'There is no `claude workflow` CLI subcommand; activation is in-session. '
                 'See adapters/claude_workflow/CAPABILITY.md for what is verified and what '
                 'is UNVERIFIED, including the /effort ultracode effort confound.',
    }


# --------------------------------------------------------------------------- definition
def load_workflow(path=DEFAULT_WORKFLOW):
    """Load and validate a ``workflow-definition/1`` document."""
    path = Path(path)
    data = json.loads(path.read_text())
    return validate_workflow(data, source=str(path))


def validate_workflow(data, source='<memory>'):
    if not isinstance(data, dict):
        raise WorkflowDefinitionError(f'{source}: workflow definition must be an object')
    if data.get('contract') != WORKFLOW_CONTRACT:
        raise WorkflowDefinitionError(
            f'{source}: incompatible contract {data.get("contract")!r}; expected {WORKFLOW_CONTRACT!r}')
    for key in ('id', 'version', 'script', 'scriptVersion'):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise WorkflowDefinitionError(f'{source}: missing {key!r}')
    nodes = data.get('nodes')
    if not isinstance(nodes, list) or not nodes:
        raise WorkflowDefinitionError(f'{source}: at least one node is required')

    seen, owned = set(), {}
    for node in nodes:
        if not isinstance(node, dict):
            raise WorkflowDefinitionError(f'{source}: every node must be an object')
        node_id = node.get('id')
        if not isinstance(node_id, str) or not node_id.strip():
            raise WorkflowDefinitionError(f'{source}: every node needs an "id"')
        if node_id in seen:
            raise WorkflowDefinitionError(f'{source}: duplicate node id {node_id!r}')
        seen.add(node_id)
        if node.get('role') not in traces.ROLES:
            raise WorkflowDefinitionError(
                f'{source}: node {node_id!r} has unknown role {node.get("role")!r}')
        if not isinstance(node.get('dependsOn', []), list):
            raise WorkflowDefinitionError(f'{source}: node {node_id!r} dependsOn must be a list')
        for path_ in node.get('owns') or []:
            if path_ in owned:
                raise WorkflowDefinitionError(
                    f'{source}: {path_!r} is owned by both {owned[path_]!r} and {node_id!r}; '
                    'exclusive file ownership is violated')
            owned[path_] = node_id

    for node in nodes:
        for dep in node.get('dependsOn') or []:
            if dep not in seen:
                raise WorkflowDefinitionError(
                    f'{source}: node {node["id"]!r} depends on unknown node {dep!r}')

    _topological_order(nodes, source)  # raises on a cycle
    return data


def _topological_order(nodes, source='<memory>'):
    by_id = {n['id']: n for n in nodes}
    order, state = [], {}

    def visit(node_id, stack):
        if state.get(node_id) == 'done':
            return
        if state.get(node_id) == 'open':
            raise WorkflowDefinitionError(
                f'{source}: dependency cycle through {" -> ".join(stack + [node_id])}')
        state[node_id] = 'open'
        for dep in sorted(by_id[node_id].get('dependsOn') or []):
            visit(dep, stack + [node_id])
        state[node_id] = 'done'
        order.append(node_id)

    for node in nodes:  # declaration order decides ties, so the plan is deterministic
        visit(node['id'], [])
    return order


# --------------------------------------------------------------------------- events
class _Emitter:
    """Builds and delivers ``trace-event/1`` events into a TraceStore or a plain list."""

    def __init__(self, sink, run_id, experiment_id, executor):
        self.sink = sink
        self.run_id = run_id
        self.experiment_id = experiment_id
        self.synthetic = bool(getattr(executor, 'SYNTHETIC', True))
        self.clock_source = getattr(executor, 'CLOCK_SOURCE', 'synthetic')
        self.describe = getattr(executor, 'describe', lambda: {})()
        self.events = []
        self._seq = 0
        self._lock = threading.Lock()

    def emit(self, node, type_, status='ok', attempt=1, source_revision=None,
             usage=None, payload=None, artifacts=None, depends_on=None, role=None):
        with self._lock:
            self._seq += 1
            seq = self._seq
        node_id = node['id'] if isinstance(node, dict) else node
        digest = sha256(f'{self.run_id}|{node_id}|{attempt}|{type_}|{seq}'.encode()).hexdigest()
        event = traces.normalize_event({
            'eventId': f'evt-{digest[:16]}',
            'experimentId': self.experiment_id,
            'runId': self.run_id,
            'nodeId': node_id,
            'attempt': attempt,
            'dependsOn': list(depends_on if depends_on is not None
                              else (node.get('dependsOn') or []) if isinstance(node, dict) else []),
            'role': role or (node.get('role') if isinstance(node, dict) else 'orchestrator'),
            'type': type_,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'clock': {'source': self.clock_source, 'uncertaintySeconds': None},
            'status': status,
            'model': dict(self.describe.get('model')
                          or {'requested': None, 'effective': None, 'verified': False}),
            'settings': dict(self.describe.get('settings')
                             or {'requested': {}, 'effective': None, 'verified': False}),
            'session': {'id': None, 'contextId': None,
                        'fresh': node.get('freshSession') if isinstance(node, dict) else None},
            'sourceRevision': source_revision,
            'artifacts': artifacts or {'inputs': [], 'outputs': []},
            'usage': usage or {'inputTokens': None, 'outputTokens': None, 'costUSD': None,
                               'durationSeconds': None, 'scope': 'self'},
            'evidence': {'ref': None, 'sha256': None,
                         'importer': IMPORTER, 'importerVersion': VERSION},
            'synthetic': self.synthetic,
            'payload': payload or {},
        })
        traces.validate_event(event)
        self.events.append(event)
        if self.sink is not None:
            with self._lock:  # a TraceStore is not thread-safe; serialize delivery
                if hasattr(self.sink, 'add'):
                    self.sink.add(event)
                else:
                    self.sink.append(event)
        return event


def _join_from_events(events, expected_node_ids):
    """Join exactly as ``traces.TraceStore.join`` does, over an in-memory event list.

    Used so the join is identical whether the sink is a TraceStore or a plain list.
    """
    started, terminal = set(), {}
    for event in events:
        if event['type'] == 'node_started':
            started.add(event['nodeId'])
        status = traces.TERMINAL_TYPES.get(event['type'])
        if status is None:
            continue
        terminal.setdefault(event['nodeId'], {}).setdefault(event['attempt'], []).append(status)
    result = traces.JoinResult()
    for node_id in expected_node_ids:
        attempts = terminal.get(node_id)
        if attempts:
            statuses = attempts[max(attempts)]
            result[node_id] = next(s for s in traces.TERMINAL_PRIORITY if s in statuses)
        elif node_id in started:
            result[node_id] = 'running'
        else:
            result[node_id] = 'missing'
    return result


# --------------------------------------------------------------------------- plan
def plan(workflow, scenario=None, workspace=None):
    """Return the declared nodes for ``workflow`` (emitted by :func:`run` as ``node_declared``)."""
    workflow = validate_workflow(workflow) if isinstance(workflow, dict) else load_workflow(workflow)
    order = _topological_order(workflow['nodes'])
    by_id = {n['id']: n for n in workflow['nodes']}
    declared = []
    for position, node_id in enumerate(order, start=1):
        node = by_id[node_id]
        declared.append({
            'nodeId': node_id,
            'role': node['role'],
            'label': node.get('label', node_id),
            'phase': node.get('phase'),
            'dependsOn': sorted(node.get('dependsOn') or []),
            'owns': list(node.get('owns') or []),
            'freshSession': bool(node.get('freshSession')),
            'chargedToCandidate': bool(node.get('chargedToCandidate')),
            'position': position,
            'workflow': {'id': workflow['id'], 'version': workflow['version'],
                         'scriptVersion': workflow['scriptVersion']},
            'scenario': scenario,
            'workspace': str(workspace) if workspace else None,
        })
    return declared


# --------------------------------------------------------------------------- aggregation
def expected_nodes(workflow):
    """The node IDs the join must account for.

    The declared ``join.expectedWorkers`` wins; otherwise every worker node; and for a
    workflow with no worker-role node at all (the single-node ``solo`` shape) every
    declared node, so that a degenerate join still accounts for something explicitly.
    """
    declared = workflow.get('join', {}).get('expectedWorkers')
    if declared:
        return list(declared)
    workers = [n['id'] for n in workflow['nodes'] if n['role'] == 'worker']
    return workers or [n['id'] for n in workflow['nodes']]


def aggregate(workflow, outputs, verdicts, join):
    """Join worker outputs and reviewer verdicts by **stable ID + sourceRevision**.

    ``outputs`` may arrive reordered, duplicated or incomplete; list position is never
    used. A failed or missing worker is accounted as failed/missing and can never become
    a successful empty result.
    """
    expected = expected_nodes(workflow)
    by_id, duplicates, conflicts, unexpected = {}, [], [], []
    for output in outputs:
        stable = output.get('stableId') or output.get('nodeId')
        if stable is None:
            conflicts.append({'stableId': None, 'reason': 'output carries no stable ID'})
            continue
        if stable not in expected and stable not in {n['id'] for n in workflow['nodes']}:
            unexpected.append(stable)
        if stable in by_id:
            if canonical(by_id[stable]) == canonical(output):
                duplicates.append(stable)
            else:
                conflicts.append({'stableId': stable,
                                  'reason': 'two different outputs claim the same stable ID'})
            continue
        by_id[stable] = output

    matched, stale, orphan = {}, [], []
    for verdict in verdicts:
        target = verdict.get('targetNodeId')
        output = by_id.get(target)
        if output is None:
            orphan.append(verdict)
            continue
        if verdict.get('sourceRevision') != output.get('sourceRevision'):
            stale.append({'targetNodeId': target,
                          'verdictRevision': verdict.get('sourceRevision'),
                          'outputRevision': output.get('sourceRevision')})
            continue
        matched.setdefault(target, []).append(verdict)

    workers = {}
    for node_id in expected:
        status = join.get(node_id, 'missing')
        output = by_id.get(node_id)
        if status != 'completed':
            workers[node_id] = {'status': status, 'output': None,
                                'verdicts': matched.get(node_id, []),
                                'reason': f'node accounted as {status}'}
        elif output is None:
            workers[node_id] = {'status': 'missing-output', 'output': None,
                                'verdicts': matched.get(node_id, []),
                                'reason': 'node completed but produced no joinable output'}
        else:
            workers[node_id] = {'status': 'completed', 'output': output,
                                'verdicts': matched.get(node_id, []), 'reason': None}

    accounted_ok = all(w['status'] == 'completed' for w in workers.values())
    #: a worker counts as unreviewed only when the workflow actually declares a reviewer
    has_reviewer = any(n['role'] == 'reviewer' for n in workflow['nodes'])
    unreviewed = sorted(node_id for node_id, entry in workers.items()
                        if entry['status'] == 'completed' and not entry['verdicts']
                        ) if has_reviewer else []
    join_ok = bool(expected) and accounted_ok and not stale and not conflicts and not unreviewed
    return {
        'joinedBy': ['stableId', 'sourceRevision'],
        'joinedByListIndex': False,
        'expectedWorkers': expected,
        'workers': workers,
        'joinOk': join_ok,
        'duplicatesIgnored': sorted(duplicates),
        'conflicts': conflicts,
        'unexpectedStableIds': sorted(set(unexpected)),
        'staleVerdicts': stale,
        'orphanVerdicts': orphan,
        'unreviewed': unreviewed,
        'missing': sorted(n for n, e in workers.items() if e['status'] in ('missing', 'missing-output')),
        'failed': sorted(n for n, e in workers.items() if e['status'] in ('failed', 'canceled')),
    }


# --------------------------------------------------------------------------- run
def run(workflow, executor, limits, trace_sink, workspace, scenario=None, run_id='run-offline',
        experiment_id=None, source_revision='rev-0', fault_plan=None, state=None, args=None):
    """Bench-controlled execution of a declared workflow through an injected executor.

    Enforces ``max_concurrency``, ``max_workers``, ``max_attempts_total`` and
    ``max_elapsed_seconds``; token/cost limits are reported with their honest label and
    never claimed as enforced. Owned subprocesses are stopped **and reaped** on timeout.
    Emits ``trace-event/1`` events into ``trace_sink`` (a ``TraceStore`` or a list).

    Returns a result dict; ``result['aggregate']['joinOk']`` is the authoritative answer
    to "did every expected worker land", and a failed or missing worker is never reported
    as a successful empty result.
    """
    workflow = validate_workflow(workflow) if isinstance(workflow, dict) else load_workflow(workflow)
    limits = Limits.coerce(limits)
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    runtime_dir = workspace / '.runtime'
    effects = EffectsLog(runtime_dir / 'effects.log')
    state = state if state is not None else RunState(runtime_dir / 'state.json')
    processes = ProcessRegistry()
    cancel = threading.Event()
    emitter = _Emitter(trace_sink, run_id, experiment_id, executor)

    # Live executors fail closed before anything else happens.
    preflight = getattr(executor, 'preflight', None)
    if preflight is not None:
        preflight()

    declared = plan(workflow, scenario, workspace)
    by_id = {n['id']: n for n in workflow['nodes']}
    order = [d['nodeId'] for d in declared]
    for entry in declared:
        emitter.emit(by_id[entry['nodeId']], 'node_declared', status='unknown',
                     source_revision=source_revision,
                     payload={'declared': entry, 'limits': limits.enforcement()})

    # -- restart: decide reuse before any work, with explicit identity checks --
    reused, rerun, replay = {}, [], []
    for node_id in order:
        record = state.completed(node_id)
        if not record:
            continue
        probe = NodeTask(run_id=run_id, node=by_id[node_id], attempt=record.get('attempt', 1),
                         source_revision=source_revision, workspace=workspace, inputs={},
                         effects=effects, processes=processes, cancel=cancel, args=dict(args or {}))
        identity = getattr(executor, 'identity', lambda task: {
            'sourceRevision': task.source_revision, 'artifactHash': None})(probe)
        ok, reason = state.reusable(node_id, identity.get('sourceRevision'),
                                    identity.get('artifactHash'))
        replay.append({'nodeId': node_id, 'reused': ok, 'reason': reason})
        (reused.setdefault(node_id, record) if ok else rerun.append(node_id))
    if replay:
        emitter.emit({'id': 'orchestrator', 'role': 'orchestrator', 'dependsOn': []}, 'restart',
                     status='ok', source_revision=source_revision,
                     payload={'replay': replay, 'reusedNodes': sorted(reused),
                              'rerunNodes': sorted(rerun), 'nativeReplayRelied': False,
                              'identityChecks': ['sourceRevision', 'artifactHash']})

    # -- max_workers: surplus worker nodes never start -------------------------
    worker_order = [n for n in order if by_id[n]['role'] == 'worker']
    admitted = set(worker_order[:limits.max_workers])
    skipped_for_workers = [n for n in worker_order[limits.max_workers:]]

    # -- shared run state ------------------------------------------------------
    lock = threading.Lock()
    attempts_used = int(state.data.get('attemptsUsed') or 0) if reused else 0
    live = 0
    peak = 0
    outputs, verdicts, node_status = [], [], {}
    faults, attempt_count = [], {}
    deadline = time.monotonic() + limits.max_elapsed_seconds
    timed_out = threading.Event()
    crashed = []

    def reserve_attempt():
        nonlocal attempts_used
        with lock:
            if attempts_used >= limits.max_attempts_total:
                return False
            attempts_used += 1
            return True

    def on_fault(milestone, node_id, attempt, kind):
        emitter.emit(by_id[node_id], 'fault', status='error', attempt=attempt,
                     source_revision=source_revision,
                     payload={'milestone': milestone, 'kind': kind, 'injected': True})

    def execute_node(node_id, inputs):
        """One node, with retries. Returns its terminal status."""
        nonlocal live, peak
        node = by_id[node_id]
        max_attempts = int((workflow.get('retry') or {}).get('maxAttemptsPerNode', 1))
        last_error = None
        for attempt in range(1, max_attempts + 1):
            if cancel.is_set() or time.monotonic() >= deadline:
                emitter.emit(node, 'node_canceled', status='error', attempt=attempt,
                             source_revision=source_revision,
                             payload={'reason': 'elapsed-time limit reached',
                                      'limit': 'max_elapsed_seconds'})
                return 'canceled'
            if not reserve_attempt():
                emitter.emit(node, 'node_canceled', status='error', attempt=attempt,
                             source_revision=source_revision,
                             payload={'reason': 'total attempt budget exhausted',
                                      'limit': 'max_attempts_total'})
                return 'canceled'
            with lock:
                live += 1
                peak = max(peak, live)
                attempt_count[node_id] = attempt
            emitter.emit(node, 'node_started', status='unknown', attempt=attempt,
                         source_revision=source_revision, payload={'inputs': sorted(inputs)})
            task = NodeTask(run_id=run_id, node=node, attempt=attempt,
                            source_revision=source_revision, workspace=workspace,
                            inputs=inputs, effects=effects, processes=processes,
                            cancel=cancel, args=dict(args or {}),
                            _fault=fault_plan, _on_fault=on_fault)
            started = time.monotonic()
            try:
                result = executor.execute(task)
            except FaultInjected as fault:
                with lock:
                    live -= 1
                    faults.append({'nodeId': node_id, 'attempt': attempt,
                                   'milestone': fault.milestone})
                    crashed.append(fault)
                cancel.set()
                emitter.emit(node, 'node_failed', status='error', attempt=attempt,
                             source_revision=source_revision,
                             payload={'reason': 'injected crash', 'milestone': fault.milestone})
                return 'failed'
            except NodeFailure as error:
                with lock:
                    live -= 1
                last_error = str(error)
                emitter.emit(node, 'node_failed', status='error', attempt=attempt,
                             source_revision=source_revision,
                             payload={'reason': last_error, 'retryable': attempt < max_attempts})
                continue
            except Exception as error:  # an executor crash is a node failure, not a silent pass
                with lock:
                    live -= 1
                last_error = f'{type(error).__name__}: {error}'
                emitter.emit(node, 'node_failed', status='error', attempt=attempt,
                             source_revision=source_revision,
                             payload={'reason': last_error, 'retryable': False})
                return 'failed'
            with lock:
                live -= 1
            elapsed = time.monotonic() - started

            node_outputs = list(result.get('outputs') or [])
            with lock:
                if node['role'] == 'reviewer':
                    verdicts.extend(node_outputs)
                else:
                    outputs.extend(node_outputs)
            state.record(node_id, attempt, result.get('sourceRevision'),
                         result.get('artifactHash'), {'outputs': node_outputs})
            state.flush(run_id, attempts_used)

            usage = result.get('usage') or {}
            emitter.emit(node, 'usage', status='ok', attempt=attempt,
                         source_revision=result.get('sourceRevision'),
                         usage={'inputTokens': _as_measurement(usage.get('inputTokens'), 'tokens'),
                                'outputTokens': _as_measurement(usage.get('outputTokens'), 'tokens'),
                                'costUSD': _as_measurement(usage.get('costUSD'), 'usd'),
                                'durationSeconds': measurement(round(elapsed, 6), 'seconds',
                                                               'measured', 'bench wall clock'),
                                'scope': 'self'},
                         payload={'chargedTo': 'candidate',
                                  'chargedToCandidate': bool(node.get('chargedToCandidate', True))})
            emitter.emit(node, 'node_completed', status='ok', attempt=attempt,
                         source_revision=result.get('sourceRevision'),
                         artifacts={'inputs': [], 'outputs': [
                             {'path': f'{node_id}/output', 'sha256': result.get('artifactHash')}]},
                         payload={'stableIds': [o.get('stableId') for o in node_outputs]})
            return 'completed'
        emitter.emit(node, 'node_failed', status='error',
                     attempt=attempt_count.get(node_id, max_attempts),
                     source_revision=source_revision,
                     payload={'reason': last_error or 'exhausted node attempts', 'final': True})
        return 'failed'

    # -- wave scheduling with a real concurrency bound -------------------------
    import concurrent.futures as _futures

    for node_id in skipped_for_workers:
        node_status[node_id] = 'skipped'
        emitter.emit(by_id[node_id], 'node_skipped', status='unknown',
                     source_revision=source_revision,
                     payload={'reason': 'max_workers limit', 'limit': 'max_workers',
                              'limitValue': limits.max_workers})

    pool = _futures.ThreadPoolExecutor(max_workers=limits.max_concurrency,
                                       thread_name_prefix='ob2-workflow')
    pending = [n for n in order if n not in node_status]
    try:
        while pending:
            ready = [n for n in pending
                     if all(node_status.get(d) in ('completed', 'reused', 'skipped')
                            for d in (by_id[n].get('dependsOn') or []))]
            if not ready:
                for node_id in pending:
                    node_status[node_id] = 'skipped'
                    emitter.emit(by_id[node_id], 'node_skipped', status='unknown',
                                 source_revision=source_revision,
                                 payload={'reason': 'a dependency did not complete'})
                break

            futures = {}
            for node_id in ready:
                if node_id in reused:
                    node_status[node_id] = 'reused'
                    record = reused[node_id]
                    payload = (record.get('payload') or {}).get('outputs') or []
                    with lock:
                        (verdicts if by_id[node_id]['role'] == 'reviewer' else outputs).extend(payload)
                    emitter.emit(by_id[node_id], 'node_completed', status='ok',
                                 attempt=record.get('attempt', 1),
                                 source_revision=record.get('sourceRevision'),
                                 artifacts={'inputs': [], 'outputs': [
                                     {'path': f'{node_id}/output',
                                      'sha256': record.get('artifactHash')}]},
                                 payload={'reusedFromState': True,
                                          'identityChecked': ['sourceRevision', 'artifactHash'],
                                          'reExecuted': False})
                    continue
                inputs = _inputs_for(by_id[node_id], outputs)
                futures[pool.submit(execute_node, node_id, inputs)] = node_id

            remaining = max(0.0, deadline - time.monotonic())
            done, not_done = _futures.wait(futures, timeout=remaining)
            for future in done:
                node_status[futures[future]] = future.result()
            if not_done:
                timed_out.set()
                cancel.set()
                for future in not_done:
                    node_status[futures[future]] = 'canceled'
                    emitter.emit(by_id[futures[future]], 'node_canceled', status='error',
                                 attempt=attempt_count.get(futures[future], 1),
                                 source_revision=source_revision,
                                 payload={'reason': 'elapsed-time limit reached',
                                          'limit': 'max_elapsed_seconds',
                                          'limitValue': limits.max_elapsed_seconds})
            pending = [n for n in pending if n not in node_status]
            if timed_out.is_set() or crashed:
                for node_id in pending:
                    node_status[node_id] = 'canceled'
                    emitter.emit(by_id[node_id], 'node_canceled', status='error',
                                 source_revision=source_revision,
                                 payload={'reason': 'run aborted before this node started'})
                pending = []
    finally:
        owned_pids = processes.pids()
        cancel.set()
        reaped = processes.reap()
        # threads are released by the cancel event; never block the bench on a hung node
        pool.shutdown(wait=False)
        state.flush(run_id, attempts_used)

    if timed_out.is_set():
        emitter.emit({'id': 'orchestrator', 'role': 'orchestrator', 'dependsOn': []}, 'note',
                     status='error', source_revision=source_revision,
                     payload={'reason': 'max_elapsed_seconds exceeded',
                              'ownedProcesses': owned_pids, 'reapedProcesses': reaped})

    join = _join_from_events(emitter.events, expected_nodes(workflow))
    aggregated = aggregate(workflow, outputs, verdicts, join)

    status = 'complete'
    if crashed:
        status = 'crashed'
    elif timed_out.is_set():
        status = 'timed-out'
    elif not aggregated['joinOk']:
        status = 'incomplete'

    result = {
        'contract': ADAPTER_CONTRACT,
        'adapter': NAME,
        'adapterVersion': VERSION,
        'runId': run_id,
        'workflow': {'id': workflow['id'], 'version': workflow['version'],
                     'scriptVersion': workflow['scriptVersion'],
                     'script': workflow['script']},
        'status': status,
        'nodeStatus': dict(node_status),
        'join': dict(join),
        'joinOk': aggregated['joinOk'],
        'aggregate': aggregated,
        'attemptsUsed': attempts_used,
        'peakConcurrency': peak,
        'skippedForWorkerLimit': skipped_for_workers,
        'timedOut': timed_out.is_set(),
        'ownedProcesses': owned_pids,
        'reapedProcesses': reaped,
        'faults': faults,
        'replay': replay,
        'reusedNodes': sorted(reused),
        'limits': limits.enforcement(),
        'executor': emitter.describe,
        'synthetic': emitter.synthetic,
        'paidCallsMade': False,
        'offlineValidation': emitter.synthetic,
        'events': emitter.events,
        'effects': effects.entries(),
    }
    if crashed:
        result['crash'] = {'milestone': crashed[0].milestone, 'nodeId': crashed[0].node_id,
                           'attempt': crashed[0].attempt}
    return result


def _inputs_for(node, outputs):
    """Inputs for a node, keyed by stable ID. The reviewer never receives a conversation."""
    if node['role'] == 'reviewer':
        worker_outputs = {o.get('stableId') or o.get('nodeId'): o for o in outputs
                          if o.get('stableId') or o.get('nodeId')}
        return {'specification': 'specification', 'workerOutputs': worker_outputs,
                'evidence': 'reproducible-evidence',
                'excluded': ['worker-conversation', 'planner-conversation',
                             'external-evaluator-output']}
    if node['role'] == 'integrator':
        return {'workerOutputs': {o.get('stableId') or o.get('nodeId'): o for o in outputs}}
    return {'specification': 'specification'}


def _as_measurement(value, unit):
    if value is None:
        return measurement(None, unit, 'unavailable', None)
    return measurement(value, unit, 'measured', 'executor report')
