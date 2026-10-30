from meetingmind.transcript import parse_timestamp, parse_transcript


def test_parse_timestamp_formats():
    assert parse_timestamp("1:23") == 83
    assert parse_timestamp("01:02:03") == 3723
    assert parse_timestamp("00:00:01,500") == 1.5


def test_bracketed_lines_and_ends_from_next_start():
    u = parse_transcript("[00:00:00] Ann: hi there\n[00:00:10] Bo: hello\n")
    assert [x.speaker for x in u] == ["Ann", "Bo"]
    assert u[0].end == 10 and u[0].duration == 10
    assert u[1].end > u[1].start


def test_untimed_lines_get_estimated_times():
    u = parse_transcript("Ann: one two three four five\nBo: ok sure\n")
    assert u[0].start == 0 and u[0].end == 2.0
    assert u[1].start == u[0].end


def test_continuation_line_joins_previous_speaker():
    u = parse_transcript("Ann: first part\nsecond part\nBo: ok then")
    assert u[0].text == "first part second part"
    assert len(u) == 2


def test_webvtt_voice_tags():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n<v Ann>Hello team</v>\n\n00:00:04.500 --> 00:00:06.000\n<v Bo>Hi Ann\n"
    u = parse_transcript(vtt)
    assert (u[0].speaker, u[0].start, u[0].end) == ("Ann", 1.0, 4.0)
    assert u[1].speaker == "Bo" and u[1].text == "Hi Ann"


def test_empty_transcript():
    assert parse_transcript("") == []
