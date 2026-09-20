# known_bad: contract-regression

Every consumer speaks v2 and the saved records migrate correctly, but `api.createNote` now refuses the legacy-shaped post the compatibility matrix says it must still accept. Intended failures: the compatibility matrix and the integrated flow, which starts from a legacy post.
