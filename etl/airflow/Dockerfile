FROM apache/airflow:2.10.5-python3.11

USER root
# spark-submit (local[*]) needs a JRE.
RUN apt-get update \
 && apt-get install -y --no-install-recommends default-jre-headless procps \
 && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/default-java

USER airflow
RUN mkdir -p /opt/airflow/data
COPY requirements.txt /tmp/requirements-otterworks.txt
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" \
      -r /tmp/requirements-otterworks.txt \
      -c "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-3.11.txt"
