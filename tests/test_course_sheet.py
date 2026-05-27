from course_engine.course_sheet import transcript_to_rows


def test_transcript_to_rows_keeps_video_reference():
    payload = {
        "video_id": "module_1_intro",
        "source_video_url": "gs://bucket/raw-videos/module_1_intro.mp4",
        "segments": [
            {"start": "00:00:01", "end": "00:01:00", "text": "Welcome to the course. This lesson explains the basics."}
        ],
    }

    rows = transcript_to_rows(payload, "gs://bucket/transcripts/module_1_intro.json", 900)

    assert len(rows) == 1
    assert rows[0]["source_video_url"] == "gs://bucket/raw-videos/module_1_intro.mp4"
    assert rows[0]["transcript_url"] == "gs://bucket/transcripts/module_1_intro.json"
    assert rows[0]["start_time"] == "00:00:01"
    assert rows[0]["end_time"] == "00:01:00"


def test_transcript_to_rows_chunks_large_lessons():
    payload = {
        "video_id": "large_video",
        "source_video_url": "gs://bucket/video.mp4",
        "segments": [
            {"start": "00:00:00", "end": "00:00:10", "text": "one two three"},
            {"start": "00:00:11", "end": "00:00:20", "text": "four five six"},
        ],
    }

    rows = transcript_to_rows(payload, "gs://bucket/transcripts/large_video.json", 3)

    assert len(rows) == 2
    assert rows[0]["lesson_text"] == "one two three"
    assert rows[1]["lesson_text"] == "four five six"
