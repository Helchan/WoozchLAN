import unittest

from gomoku_lan.net.protocol import decode_frames, encode_frame


class ProtocolTests(unittest.TestCase):
    def test_encode_decode_single(self) -> None:
        msg = {"type": "hello", "x": 1, "s": "中文"}
        frame = encode_frame(msg)
        buf = bytearray(frame)
        out = decode_frames(buf)
        self.assertEqual(out, [msg])
        self.assertEqual(buf, bytearray())

    def test_decode_partial(self) -> None:
        msg = {"type": "peers", "items": [1, 2, 3]}
        frame = encode_frame(msg)
        buf = bytearray()
        buf.extend(frame[:3])
        self.assertEqual(decode_frames(buf), [])
        buf.extend(frame[3:])
        self.assertEqual(decode_frames(buf), [msg])


if __name__ == "__main__":
    unittest.main()

