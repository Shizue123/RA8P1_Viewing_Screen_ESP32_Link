from __future__ import annotations

import unittest

from cloud.app.agent_service.asr import transcribe_audio
from cloud.app.config import Settings


class AsrTest(unittest.TestCase):
    def test_mock_asr_uses_header_transcript_for_binary_audio(self) -> None:
        transcription = transcribe_audio(
            settings=Settings(asr_provider="mock"),
            audio=b"\x00\x01binary",
            filename="audio.wav",
            content_type="audio/wav",
            mock_transcript="温度超过30度时蜂鸣",
        )

        self.assertEqual("温度超过30度时蜂鸣", transcription.text)
        self.assertEqual("mock", transcription.provider)

    def test_mock_asr_can_decode_text_payload(self) -> None:
        transcription = transcribe_audio(
            settings=Settings(asr_provider="mock"),
            audio="温度超过30度时蜂鸣".encode("utf-8"),
            filename="audio.txt",
            content_type="text/plain",
        )

        self.assertEqual("温度超过30度时蜂鸣", transcription.text)

    def test_openai_asr_requires_api_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
            transcribe_audio(
                settings=Settings(asr_provider="openai", openai_api_key=""),
                audio=b"RIFF",
                filename="audio.wav",
                content_type="audio/wav",
            )


if __name__ == "__main__":
    unittest.main()
