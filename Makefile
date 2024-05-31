lint:
	python -m isort .
	python -m black .
	python -m pylama .
	python -m pydocstyle .
