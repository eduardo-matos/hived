import json
import unittest

import mock
from amqp import AMQPError
import amqp

from hived.queue import (ExternalQueue, ConnectionError, MAX_TRIES, SerializationError, META_FIELD)


class ExternalQueueTest(unittest.TestCase):
    def setUp(self):

        _delivery_info = {'delivery_tag': 'delivery_tag'}

        self.message = mock.MagicMock()
        self.message.body = "{}"
        self.message.delivery_info = _delivery_info


        self.channel_mock = mock.MagicMock()
        self.channel_mock.basic_get.return_value = self.message

        self.connection = mock.MagicMock()
        self.connection.channel.return_value = self.channel_mock

        self.connection_cls_patcher = mock.patch('amqp.Connection',
                                                 return_value=self.connection)
        self.connection_cls_mock = self.connection_cls_patcher.start()

        self.external_queue = ExternalQueue('localhost', 'username', 'pwd',
                                            exchange='default_exchange',
                                            queue_name='default_queue')

    def tearDown(self):
        self.connection_cls_patcher.stop()

    def test__try_connects_if_disconnected(self):
        self.channel_mock.method.return_value = 'rv'
        rv = self.external_queue._try('method', arg='value')

        self.assertEqual(self.connection_cls_mock.call_count, 1)
        self.assertEqual(self.channel_mock.method.call_args_list,
                         [mock.call(arg='value')])
        self.assertEqual(rv, 'rv')

    def test__try_tries_up_to_max_tries(self):
        self.channel_mock.method.side_effect = [AMQPError, AMQPError, 'rv']
        rv = self.external_queue._try('method')

        self.assertEqual(self.channel_mock.method.call_count, MAX_TRIES)
        self.assertEqual(rv, 'rv')

    def test__try_doesnt_try_more_than_max_tries(self):
        self.channel_mock.method.side_effect = [AMQPError, AMQPError, AMQPError, 'rv']
        self.assertRaises(ConnectionError, self.external_queue._try, 'method')

    def test_put_uses_default_exchange_if_not_supplied(self):
        amqp_msg = amqp.basic_message.Message("body",
                                              delivery_mode=2,
                                              content_type='application/json')

        self.external_queue.put(body='body')
        self.assertEqual(self.channel_mock.basic_publish.call_args_list,
                         [mock.call(msg=amqp_msg,
                                    exchange='default_exchange',
                                    routing_key='')])

    def test_put_serializes_message_if_necessary(self):
        message_dict = {'key': 'value'}
        amqp_msg = amqp.basic_message.Message(json.dumps(message_dict),
                                              delivery_mode=2,
                                              content_type='application/json')

        self.external_queue.put(message_dict=message_dict,
                                exchange='exchange',
                                routing_key='routing_key')
        self.assertEqual(self.channel_mock.basic_publish.call_args_list,
                         [mock.call(msg=amqp_msg,
                                    exchange='exchange',
                                    routing_key='routing_key')])

    def test_put_raises_serialization_error_if_message_cant_be_serialized_to_json(self):
        self.assertRaises(SerializationError, self.external_queue.put, message_dict=ValueError)

    def test_get_uses_default_queue_if_not_supplied(self):
        self.external_queue.get()
        self.assertEqual(self.channel_mock.basic_get.call_args_list, [mock.call(queue='default_queue')])

    def test_get_returns_none_if_block_is_false_and_queue_is_empty(self):
        self.channel_mock.basic_get.return_value = None
        rv = self.external_queue.get(block=False)
        self.assertEqual(rv, (None, None))

    def test_get_deserializes_the_message_body_and_sets_meta_field(self):
        message, ack = self.external_queue.get()
        self.assertEqual(message, {META_FIELD: {}})
        self.assertEqual(ack, 'delivery_tag')

    def test_get_raises_serialization_error_if_message_body_cant_be_parsed(self):
        self.message.body = ValueError
        self.assertRaises(SerializationError, self.external_queue.get)

    def test_get_sleeps_and_tries_again_until_queue_is_not_empty(self):
        empty_rv = None
        self.channel_mock.basic_get.side_effect = [empty_rv, empty_rv, self.message]
        with mock.patch('time.sleep') as sleep:
            _, delivery_tag = self.external_queue.get(queue_name='queue_name')

            self.assertEqual(self.channel_mock.basic_get.call_args_list,
                             [mock.call(queue='queue_name'),
                              mock.call(queue='queue_name'),
                              mock.call(queue='queue_name')])
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(delivery_tag, 'delivery_tag')

    def test_ack_ignores_connection_errors(self):
        self.external_queue.channel = self.channel_mock
        self.channel_mock.basic_ack.side_effect = AMQPError
        self.external_queue.ack('delivery_tag')

    def test_reject_ignores_connection_errors(self):
        self.external_queue.channel = self.channel_mock
        self.channel_mock.basic_reject.side_effect = AMQPError
        self.external_queue.reject('delivery_tag')


if __name__ == '__main__':
    unittest.main()
