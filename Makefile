.PHONY: run test clean docker

run:            ## start the server on http://127.0.0.1:8787
	python app.py

test:           ## run the integration test-suite
	python -m unittest discover -s tests -v

docker:         ## build & run the container with a persistent volume
	docker build -t syncro .
	docker run --rm -p 8787:8787 -v "$$PWD/syncro_data:/app/syncro_data" syncro

clean:          ## remove caches (never touches syncro_data/)
	rm -rf .pytest_cache **/__pycache__
