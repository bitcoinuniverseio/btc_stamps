import unittest
from unittest.mock import MagicMock, Mock, patch

import zmq

from index_core import zmq_utils
from index_core.zmq_utils import ZMQNotifier


class TestZMQUtils(unittest.TestCase):
    """Test ZMQ utility functions and error handling."""

    def setUp(self):
        """Set up test fixtures."""
        self.zmq_notifier = ZMQNotifier()
        zmq_utils._node_check.update(port=None, result=None, at=0.0)

    def tearDown(self):
        """Clean up after tests."""
        self.zmq_notifier.cleanup()

    @patch("index_core.zmq_utils.config.QUICKNODE_ENDPOINT", None)
    @patch("index_core.zmq_utils.zmq.Context")
    @patch("index_core.zmq_utils.ZMQNotifier._node_publishes_rawblock", return_value=True)
    def test_check_zmq_ports_success(self, _mock_published, mock_context):
        """Test successful ZMQ port checking."""
        mock_socket = Mock()
        mock_context_instance = Mock()
        mock_context_instance.socket.return_value = mock_socket
        mock_context.return_value = mock_context_instance

        with patch("index_core.zmq_utils.config.ZMQ_HOST", "localhost"), patch(
            "index_core.zmq_utils.config.BACKEND_CONNECT", "localhost"
        ), patch("index_core.zmq_utils.config.ZMQ_BLOCK_PORT", 29333):

            result = self.zmq_notifier.check_zmq_ports()

            self.assertTrue(result)
            self.assertTrue(self.zmq_notifier._is_active)
            mock_socket.connect.assert_called_once_with("tcp://localhost:29333")
            mock_socket.setsockopt.assert_any_call(zmq.SUBSCRIBE, b"rawblock")

    @patch("index_core.zmq_utils.config.QUICKNODE_ENDPOINT", None)
    @patch("index_core.zmq_utils.zmq.Context")
    @patch("index_core.zmq_utils.ZMQNotifier._node_publishes_rawblock", return_value=False)
    def test_check_zmq_ports_node_without_zmq(self, _mock_published, mock_context):
        """A node publishing no rawblock means polling, although connect would succeed."""
        mock_socket = Mock()
        mock_context.return_value.socket.return_value = mock_socket

        with patch("index_core.zmq_utils.config.ZMQ_BLOCK_PORT", 9333):
            result = self.zmq_notifier.check_zmq_ports()

        self.assertFalse(result)
        self.assertFalse(self.zmq_notifier._is_active)
        mock_socket.connect.assert_not_called()

    def test_node_publishes_rawblock_reads_getzmqnotifications(self):
        """Only a pubrawblock on the configured port counts."""
        backend = Mock()

        def check(answer):
            zmq_utils._node_check.update(port=None, result=None, at=0.0)
            if isinstance(answer, Exception):
                backend.rpc.side_effect = answer
            else:
                backend.rpc.side_effect = None
                backend.rpc.return_value = answer
            return self.zmq_notifier._node_publishes_rawblock(9333)

        with patch("index_core.backend.Backend", return_value=backend):
            self.assertFalse(check([]))
            self.assertFalse(check([{"type": "pubhashtx", "address": "tcp://127.0.0.1:9333"}]))
            self.assertFalse(check([{"type": "pubrawblock", "address": "tcp://127.0.0.1:9334"}]))
            self.assertTrue(check([{"type": "pubrawblock", "address": "tcp://127.0.0.1:9333"}]))
            self.assertFalse(check(RuntimeError("rpc down")))

    @patch("index_core.zmq_utils.config.QUICKNODE_ENDPOINT", None)
    def test_node_check_asks_the_node_once_per_ttl(self):
        """The polling loop re-checks often; the node is asked once per TTL."""
        backend = Mock()
        backend.rpc.return_value = []
        with patch("index_core.backend.Backend", return_value=backend):
            for _ in range(5):
                self.assertFalse(self.zmq_notifier.check_zmq_ports())
        self.assertEqual(backend.rpc.call_count, 1)

    @patch("index_core.zmq_utils.config.QUICKNODE_ENDPOINT", "some-endpoint")
    def test_check_zmq_ports_quicknode_disabled(self):
        """Test ZMQ is disabled when using Quicknode."""
        result = self.zmq_notifier.check_zmq_ports()

        self.assertFalse(result)
        self.assertFalse(self.zmq_notifier._is_active)

    @patch("index_core.zmq_utils.config.QUICKNODE_ENDPOINT", None)
    @patch("index_core.zmq_utils.zmq.Context")
    @patch("index_core.zmq_utils.ZMQNotifier._node_publishes_rawblock", return_value=True)
    def test_check_zmq_ports_connection_failure(self, _mock_published, mock_context):
        """Test ZMQ port checking with connection failure."""
        mock_socket = Mock()
        mock_socket.connect.side_effect = zmq.error.ZMQError("Connection failed")
        mock_context_instance = Mock()
        mock_context_instance.socket.return_value = mock_socket
        mock_context.return_value = mock_context_instance

        with patch("index_core.zmq_utils.config.ZMQ_HOST", "localhost"), patch(
            "index_core.zmq_utils.config.BACKEND_CONNECT", "localhost"
        ), patch("index_core.zmq_utils.config.ZMQ_BLOCK_PORT", 29333):

            result = self.zmq_notifier.check_zmq_ports()

            self.assertFalse(result)
            self.assertFalse(self.zmq_notifier._is_active)

    def test_wait_for_notification_inactive(self):
        """Test waiting for notification when ZMQ is inactive."""
        self.zmq_notifier._is_active = False

        result = self.zmq_notifier.wait_for_notification()

        self.assertIsNone(result)

    @patch("index_core.zmq_utils.config.QUICKNODE_ENDPOINT", None)
    def test_wait_for_notification_valid_utf8(self):
        """Test waiting for notification with valid UTF-8 data."""
        # Set up mock socket
        mock_socket = Mock()
        mock_socket.poll.return_value = zmq.POLLIN
        mock_socket.recv_multipart.return_value = [b"rawblock", b"binary_block_data", b"12345"]  # topic  # body  # sequence

        self.zmq_notifier.socket = mock_socket
        self.zmq_notifier._is_active = True

        result = self.zmq_notifier.wait_for_notification()

        self.assertIsNotNone(result)
        topic, body, seq = result
        self.assertEqual(topic, b"rawblock")
        self.assertEqual(body, b"binary_block_data")
        self.assertEqual(seq, b"12345")

    @patch("index_core.zmq_utils.config.QUICKNODE_ENDPOINT", None)
    def test_wait_for_notification_invalid_utf8_topic(self):
        """Test waiting for notification with invalid UTF-8 in topic - should handle gracefully."""
        # Set up mock socket with invalid UTF-8 in topic
        mock_socket = Mock()
        mock_socket.poll.return_value = zmq.POLLIN
        mock_socket.recv_multipart.return_value = [
            b"\x80\x81\x82",  # invalid UTF-8 topic
            b"binary_block_data",  # body
            b"12345",  # sequence
        ]

        self.zmq_notifier.socket = mock_socket
        self.zmq_notifier._is_active = True

        # This should handle the UTF-8 decode error gracefully and return the notification
        result = self.zmq_notifier.wait_for_notification()

        # Should return the notification with replacement characters used for invalid UTF-8
        self.assertIsNotNone(result)
        topic, body, seq = result
        self.assertEqual(topic, b"\x80\x81\x82")
        self.assertEqual(body, b"binary_block_data")
        self.assertEqual(seq, b"12345")
        self.assertTrue(self.zmq_notifier._is_active)  # Should remain active

    @patch("index_core.zmq_utils.config.QUICKNODE_ENDPOINT", None)
    def test_wait_for_notification_invalid_utf8_sequence(self):
        """Test waiting for notification with invalid UTF-8 in sequence - should handle gracefully."""
        # Set up mock socket with invalid UTF-8 in sequence
        mock_socket = Mock()
        mock_socket.poll.return_value = zmq.POLLIN
        mock_socket.recv_multipart.return_value = [
            b"rawblock",  # valid topic
            b"binary_block_data",  # body
            b"\x80\x81\x82",  # invalid UTF-8 sequence
        ]

        self.zmq_notifier.socket = mock_socket
        self.zmq_notifier._is_active = True

        # This should handle the UTF-8 decode error gracefully and return the notification
        result = self.zmq_notifier.wait_for_notification()

        # Should return the notification with replacement characters used for invalid UTF-8
        self.assertIsNotNone(result)
        topic, body, seq = result
        self.assertEqual(topic, b"rawblock")
        self.assertEqual(body, b"binary_block_data")
        self.assertEqual(seq, b"\x80\x81\x82")
        self.assertTrue(self.zmq_notifier._is_active)  # Should remain active

    @patch("index_core.zmq_utils.config.QUICKNODE_ENDPOINT", None)
    def test_wait_for_notification_no_events(self):
        """Test waiting for notification with no events."""
        mock_socket = Mock()
        mock_socket.poll.return_value = 0  # No events

        self.zmq_notifier.socket = mock_socket
        self.zmq_notifier._is_active = True

        result = self.zmq_notifier.wait_for_notification()

        self.assertIsNone(result)

    @patch("index_core.zmq_utils.config.QUICKNODE_ENDPOINT", None)
    def test_wait_for_notification_zmq_error(self):
        """Test waiting for notification with ZMQ error."""
        mock_socket = Mock()
        mock_socket.poll.side_effect = zmq.error.ZMQError("Socket error")

        self.zmq_notifier.socket = mock_socket
        self.zmq_notifier._is_active = True

        result = self.zmq_notifier.wait_for_notification()

        self.assertIsNone(result)
        self.assertFalse(self.zmq_notifier._is_active)  # Should be cleaned up

    def test_cleanup(self):
        """Test ZMQ resource cleanup."""
        # Set up mock objects
        mock_socket = Mock()
        mock_context = Mock()

        self.zmq_notifier.socket = mock_socket
        self.zmq_notifier.context = mock_context
        self.zmq_notifier._is_active = True

        self.zmq_notifier.cleanup()

        mock_socket.close.assert_called_once()
        mock_context.term.assert_called_once()
        self.assertIsNone(self.zmq_notifier.socket)
        self.assertIsNone(self.zmq_notifier.context)
        self.assertFalse(self.zmq_notifier._is_active)

    def test_stop(self):
        """Test stopping ZMQ notifier."""
        # Set up mock objects
        mock_socket = Mock()
        mock_context = Mock()

        self.zmq_notifier.socket = mock_socket
        self.zmq_notifier.context = mock_context
        self.zmq_notifier._is_active = True

        self.zmq_notifier.stop()

        mock_socket.close.assert_called_once()
        mock_context.term.assert_called_once()
        self.assertIsNone(self.zmq_notifier.socket)
        self.assertIsNone(self.zmq_notifier.context)
        self.assertFalse(self.zmq_notifier._is_active)

    def test_timeout_clamping(self):
        """Test that timeout is properly clamped to maximum value."""
        mock_socket = Mock()
        mock_socket.poll.return_value = 0

        self.zmq_notifier.socket = mock_socket
        self.zmq_notifier._is_active = True

        # Test with timeout > 1000ms
        self.zmq_notifier.wait_for_notification(5000)

        # Should be clamped to 1000ms
        mock_socket.poll.assert_called_with(1000)

    @patch("index_core.zmq_utils.config.QUICKNODE_ENDPOINT", None)
    def test_exact_production_error_scenario(self):
        """Test the exact UTF-8 error scenario from production logs."""
        # The exact error: "'utf-8' codec can't decode byte 0x80 in position 0: invalid start byte"
        mock_socket = Mock()
        mock_socket.poll.return_value = zmq.POLLIN
        mock_socket.recv_multipart.return_value = [
            b"\x80rawblock",  # Byte 0x80 at position 0 - exact error from logs
            b"binary_block_data",
            b"12345",
        ]

        self.zmq_notifier.socket = mock_socket
        self.zmq_notifier._is_active = True

        # This should handle the exact production error gracefully
        result = self.zmq_notifier.wait_for_notification()

        # Should return the notification successfully
        self.assertIsNotNone(result)
        topic, body, seq = result
        self.assertEqual(topic, b"\x80rawblock")
        self.assertEqual(body, b"binary_block_data")
        self.assertEqual(seq, b"12345")
        self.assertTrue(self.zmq_notifier._is_active)


if __name__ == "__main__":
    unittest.main()
