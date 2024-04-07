import json
import logging
import os
from typing import Any, Type

import kombu
from kombu import Connection, Exchange, Message, Producer, Queue
from kombu.mixins import ConsumerMixin


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CustomWorker(ConsumerMixin):
    def __init__(self, connection: Connection):
        self.connection = connection
        self.error_exchange = Exchange('errors', type='direct')
        self.error_producer = Producer(
            exchange=self.error_exchange, channel=self.connection.channel(), routing_key='errors'
        )
        self.task_queues = self.setup_queues()

    def setup_queues(self) -> list[Queue]:
        task_exchange = Exchange('stuff', type='direct')
        error_queue = Queue('errors', self.error_exchange, routing_key='errors')
        stuff_queue = Queue(
            'stuff',
            task_exchange,
            routing_key='stuff',
            queue_arguments={
                'x-dead-letter-exchange': 'stuff-retry',
                'x-dead-letter-routing-key': 'stuff-retry',
                'x-queue-type': 'classic',
            },
        )
        stuff_retry_queue = Queue(
            'stuff-retry',
            Exchange('stuff-retry', type='direct'),
            routing_key='stuff-retry',
            queue_arguments={
                'x-dead-letter-exchange': 'stuff',
                'x-dead-letter-routing-key': 'stuff',
                'x-queue-type': 'classic',
                'x-message-ttl': 60000,  # 1 minute
            },
            durable=True,
            auto_delete=False,
        )
        return [error_queue, stuff_queue, stuff_retry_queue]

    def get_consumers(self, consumer_klass: Type[kombu.Consumer], _: Any) -> list[kombu.Consumer]:
        return [consumer_klass(queues=[self.task_queues[1]], callbacks=[self.process_message])]

    def process_message(self, body: str, message: Message) -> None:
        try:
            event = json.loads(body)
            logger.info(f'Received message: {event}')
        except json.JSONDecodeError:
            logger.error('Failed to decode message', exc_info=True)
            message.reject()
            return

        n = event.get('n', 0)

        if 'x-death' in message.headers and message.headers.get('x-death', [])[0].get('count', 0) == 3:
            logger.info(f'Moved to error exchange: {message.headers} {body}')
            self.error_producer.publish(body)
            message.ack()
            return

        if n != 3:
            logger.info(f'Processed message: {message.headers} {body}')
            message.ack()
        else:
            logger.info(f'Reject message: {message.headers} {body}')
            message.reject(requeue=False)


def main() -> None:
    try:
        connection = Connection(
            os.getenv('RABBITMQ_URL', 'amqp://localhost:5672//'),
            userid=os.getenv('RABBITMQ_USER', 'admin'),
            password=os.getenv('RABBITMQ_PASSWORD', 'admin'),
            connect_retry=True,
        )
        worker = CustomWorker(
            connection,
        )
        worker.run()
    except KeyboardInterrupt:
        logger.info('Exiting...')
    except Exception as e:
        logger.error(f'Unhandled exception: {e}', exc_info=True)
    finally:
        connection.close()


if __name__ == '__main__':
    main()
