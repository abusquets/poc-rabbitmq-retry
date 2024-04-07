# POC-RABBITMQ-RETRY

env for vscode
```
poetry env use 3.12
poetry install
```

Start service

```
docker-compose up
```

Publish message

```
docker-compose exec worker1 python publish_message.py
```
