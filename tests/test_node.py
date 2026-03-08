import queue
import time
import unittest

from gamehall.net.discovery import _probe_targets
from gamehall.net.node import Node, NodeConfig


class NodeTests(unittest.TestCase):
    def test_two_nodes_handshake(self) -> None:
        q1: "queue.Queue[object]" = queue.Queue()
        q2: "queue.Queue[object]" = queue.Queue()

        n1 = Node(NodeConfig(peer_id="n1", nickname="A", ip="127.0.0.1", udp_port=37020), on_event=q1.put, enable_discovery=False)
        n2 = Node(NodeConfig(peer_id="n2", nickname="B", ip="127.0.0.1", udp_port=37021), on_event=q2.put, enable_discovery=False)
        n1.start()
        n2.start()
        try:
            n1.connect_to(n2.local_ip, n2.listen_addr.port)  # type: ignore[union-attr]

            deadline = time.time() + 3.0
            while time.time() < deadline:
                p1 = {p.peer_id for p in n1.peers_snapshot()}
                p2 = {p.peer_id for p in n2.peers_snapshot()}
                if "n2" in p1 and "n1" in p2:
                    break
                time.sleep(0.05)

            self.assertIn("n2", {p.peer_id for p in n1.peers_snapshot()})
            self.assertIn("n1", {p.peer_id for p in n2.peers_snapshot()})
        finally:
            n1.stop()
            n2.stop()

    def test_probe_targets_include_cross_subnet_addresses(self) -> None:
        targets = _probe_targets("10.235.96.8", 37020)
        target_ips = [t[0] for t in targets]
        self.assertIn("255.255.255.255", target_ips)
        self.assertIn("10.235.255.255", target_ips)
        self.assertIn("10.255.255.255", target_ips)


if __name__ == "__main__":
    unittest.main()
