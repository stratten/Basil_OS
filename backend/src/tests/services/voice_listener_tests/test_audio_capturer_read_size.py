import subprocess
import sys
import time

from api.services.wake_word.audio_capturer import (
    AUDIO_READ_BYTES,
    TARGET_BYTES_PER_CHUNK,
    TARGET_CHANNELS,
    TARGET_SAMPLE_RATE,
    TARGET_SAMPLE_WIDTH,
)

BYTES_PER_SECOND = TARGET_SAMPLE_RATE * TARGET_SAMPLE_WIDTH * TARGET_CHANNELS


def test_one_read_is_at_most_one_hundred_milliseconds_of_audio():
    assert AUDIO_READ_BYTES / BYTES_PER_SECOND <= 0.1


def test_one_read_is_a_whole_number_of_samples():
    assert AUDIO_READ_BYTES % (TARGET_SAMPLE_WIDTH * TARGET_CHANNELS) == 0


def test_one_read_is_one_wake_word_chunk():
    assert AUDIO_READ_BYTES == TARGET_BYTES_PER_CHUNK


def test_a_buffered_pipe_read_waits_for_the_full_size_so_the_read_size_sets_the_delivery_interval():
    """Documents why the read size matters: a buffered pipe's read(n) holds back data until n bytes have arrived."""
    producer = (
        "import sys, time\n"
        "for _ in range(6):\n"
        "    sys.stdout.buffer.write(b'x' * 1000)\n"
        "    sys.stdout.buffer.flush()\n"
        "    time.sleep(0.05)\n"
    )
    process = subprocess.Popen([sys.executable, "-c", producer], stdout=subprocess.PIPE)
    start = time.monotonic()
    first_read = process.stdout.read(4000)
    elapsed = time.monotonic() - start
    process.stdout.read()
    process.wait()

    assert len(first_read) == 4000
    assert elapsed >= 0.15
