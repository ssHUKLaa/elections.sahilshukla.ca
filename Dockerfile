FROM scratch
FROM python:3.10.6-alpine
WORKDIR .
RUN apk update
RUN apk add make automake gcc g++ subversion python3-dev
COPY requirements.txt .

RUN pip install -r requirements.txt
COPY datavisualize.py .
COPY loadpollingdata.py .
COPY 2024_runForecast.py .
COPY /assets/. /assets/
ENTRYPOINT [ “python” ]
CMD [“datavisualize.py” ]
EXPOSE 8050