.PHONY: run test eval install lint

install:
	pip install -r requirements.txt

run:
	python main.py

test:
	pytest tests/ -v

eval:
	python evals/eval_runner.py

lint:
	ruff check src/
