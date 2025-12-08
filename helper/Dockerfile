FROM python:3.12-slim


WORKDIR /app


RUN apt-get update && apt-get install -y --no-install-recommends \
	build-essential \
	cmake \
	libopenblas-dev \
	&& rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir flask requests llama-cpp-python


COPY . /app
ENV FLASK_APP=app.py
CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]
