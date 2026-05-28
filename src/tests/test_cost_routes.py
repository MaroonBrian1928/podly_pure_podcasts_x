from datetime import datetime
from typing import Any

from app.extensions import db
from app.models import Feed, ModelCall, Post, ProcessingJob, User, UserFeed
from app.routes import cost_routes
from app.routes.cost_routes import _model_call_cost, costs_bp


def test_admin_costs_uses_litellm_tokens_and_configured_audio_rates(
    app: Any, monkeypatch: Any
) -> None:
    app.register_blueprint(costs_bp)
    monkeypatch.setattr(cost_routes, "require_admin", lambda _action: (None, None))
    monkeypatch.setattr(
        cost_routes,
        "read_combined",
        lambda: {
            "app": {
                "cost_rate_per_hour": 0.04,
                "whisper_cost_rate_per_hour": 0.04,
                "ina_cost_rate_per_hour": 0.02,
            }
        },
    )

    with app.app_context():
        feed = Feed(title="Cost Feed", rss_url="https://example.com/feed.xml")
        user_a = User(username="a", password_hash="x", role="user")
        user_b = User(username="b", password_hash="x", role="user")
        db.session.add_all([feed, user_a, user_b])
        db.session.flush()
        db.session.add_all(
            [
                UserFeed(feed_id=feed.id, user_id=user_a.id),
                UserFeed(feed_id=feed.id, user_id=user_b.id),
            ]
        )
        post = Post(
            feed_id=feed.id,
            guid="cost-guid",
            download_url="https://example.com/audio.mp3",
            title="Cost Episode",
            duration=3600,
        )
        db.session.add(post)
        db.session.flush()
        db.session.add(
            ProcessingJob(
                post_guid=post.guid,
                status="completed",
                completed_at=datetime(2026, 5, 15, 12, 0, 0),
            )
        )
        db.session.add_all(
            [
                ModelCall(
                    post_id=post.id,
                    first_segment_sequence_num=0,
                    last_segment_sequence_num=1,
                    model_name="gpt-4o-mini",
                    prompt="classify",
                    status="success",
                    prompt_tokens=1_000_000,
                    cached_prompt_tokens=500_000,
                    completion_tokens=250_000,
                    total_tokens=1_750_000,
                ),
                ModelCall(
                    post_id=post.id,
                    first_segment_sequence_num=0,
                    last_segment_sequence_num=-1,
                    model_name="whisper-large-v3-turbo",
                    prompt="Whisper transcription job",
                    status="success",
                ),
                ModelCall(
                    post_id=post.id,
                    first_segment_sequence_num=0,
                    last_segment_sequence_num=-1,
                    model_name="ina:speech_music_noise",
                    prompt="INA speech/music/noise",
                    status="success",
                ),
            ]
        )
        db.session.commit()

        response = app.test_client().get("/api/admin/costs?year=2026&month=5")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total_llm_cost"] == 0.3375
    assert payload["total_whisper_cost"] == 0.04
    assert payload["total_ina_cost"] == 0.02
    assert payload["total_cost"] == 0.3975
    assert payload["feeds"][0]["llm_cost"] == 0.3375
    assert payload["feeds"][0]["whisper_cost"] == 0.04
    assert payload["feeds"][0]["ina_cost"] == 0.02
    assert payload["users"][0]["monthly_cost"] == 0.1988
    assert payload["users"][1]["monthly_cost"] == 0.1988


def test_model_call_cost_prices_gemini_flex_at_half_base_rate() -> None:
    call = ModelCall(
        model_name="gemini/gemini-3-flash-preview",
        service_tier="flex",
        prompt_tokens=1_000_000,
        cached_prompt_tokens=500_000,
        completion_tokens=250_000,
    )

    # LiteLLM's Gemini 3 Flash Preview table has base rates
    # input=0.50/M, cache-read=0.05/M, output=3.00/M. It does not currently
    # expose *_flex keys, so Podly applies the documented Flex 50% discount.
    assert _model_call_cost(call) == 0.6375
