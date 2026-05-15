use anyhow::{anyhow, Context, Result};
use chrono::{DateTime, NaiveDateTime, Utc};
use clap::{ArgAction, Args, Parser, Subcommand, ValueEnum};
use id3::frame::{Chapter as Id3Chapter, Content, Frame, TableOfContents};
use id3::{Encoding as Id3Encoding, Tag, TagLike, Version};
use regex::Regex;
use rusqlite::{Connection, OpenFlags};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Mutex, OnceLock};

#[derive(Parser)]
#[command(name = "podly_tools")]
#[command(about = "Short-lived Podly helper process for file-heavy work")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    Audio(AudioCommand),
    Feed(FeedCommand),
    Jobs(JobsCommand),
    Stats(StatsCommand),
    Transcript(TranscriptCommand),
    Chapters(ChaptersCommand),
}

#[derive(Args)]
struct AudioCommand {
    #[command(subcommand)]
    command: AudioSubcommand,
}

#[derive(Subcommand)]
enum AudioSubcommand {
    Probe(AudioProbeArgs),
    Cut(AudioCutArgs),
    Bleep(AudioBleepArgs),
    Split(AudioSplitArgs),
}

#[derive(Args)]
struct AudioProbeArgs {
    #[arg(long)]
    input: PathBuf,
}

#[derive(Args)]
struct AudioCutArgs {
    #[arg(long)]
    input: PathBuf,
    #[arg(long)]
    output: PathBuf,
    #[arg(long = "windows-json")]
    windows_json: PathBuf,
    #[arg(long)]
    mode: CutMode,
    #[arg(long = "fade-ms")]
    fade_ms: u32,
    #[arg(long)]
    encoding: Encoding,
    #[arg(long = "cbr-bitrate-bps")]
    cbr_bitrate_bps: Option<u64>,
    #[arg(long = "vbr-quality")]
    vbr_quality: Option<u8>,
}

#[derive(Args)]
struct AudioBleepArgs {
    #[arg(long)]
    input: PathBuf,
    #[arg(long)]
    output: PathBuf,
    #[arg(long = "windows-json")]
    windows_json: PathBuf,
    #[arg(long = "beep-frequency-hz")]
    beep_frequency_hz: u32,
    #[arg(long = "beep-volume")]
    beep_volume: f32,
    #[arg(long = "duck-volume")]
    duck_volume: f32,
    #[arg(long = "fade-ms", default_value_t = 5)]
    fade_ms: u32,
    #[arg(long)]
    encoding: Encoding,
    #[arg(long = "cbr-bitrate-bps")]
    cbr_bitrate_bps: Option<u64>,
    #[arg(long = "vbr-quality")]
    vbr_quality: Option<u8>,
}

#[derive(Args)]
struct AudioSplitArgs {
    #[arg(long)]
    input: PathBuf,
    #[arg(long = "out-dir")]
    out_dir: PathBuf,
    #[arg(long = "chunk-size-bytes")]
    chunk_size_bytes: u64,
}

#[derive(Clone, ValueEnum)]
enum CutMode {
    Fade,
    Exact,
}

#[derive(Clone, ValueEnum)]
enum Encoding {
    Vbr,
    Cbr,
}

#[derive(Clone)]
struct EncodingOptions {
    mode: Encoding,
    cbr_bitrate_bps: Option<u64>,
    vbr_quality: Option<u8>,
}

impl EncodingOptions {
    fn new(mode: Encoding, cbr_bitrate_bps: Option<u64>, vbr_quality: Option<u8>) -> Self {
        Self {
            mode,
            cbr_bitrate_bps,
            vbr_quality,
        }
    }
}

#[derive(Args)]
struct FeedCommand {
    #[command(subcommand)]
    command: FeedSubcommand,
}

#[derive(Subcommand)]
enum FeedSubcommand {
    Render(FeedRenderArgs),
    RenderAggregate(FeedRenderAggregateArgs),
    RefreshPlan(FeedRefreshPlanArgs),
}

#[derive(Args)]
struct JobsCommand {
    #[command(subcommand)]
    command: JobsSubcommand,
}

#[derive(Subcommand)]
enum JobsSubcommand {
    Active(JobsListArgs),
    All(JobsListArgs),
    Status(JobsStatusArgs),
}

#[derive(Args)]
struct JobsListArgs {
    #[arg(long)]
    db: PathBuf,
    #[arg(long, default_value_t = 100)]
    limit: i64,
}

#[derive(Args)]
struct JobsStatusArgs {
    #[arg(long)]
    db: PathBuf,
}

#[derive(Args)]
struct StatsCommand {
    #[command(subcommand)]
    command: StatsSubcommand,
}

#[derive(Subcommand)]
enum StatsSubcommand {
    Render(StatsRenderArgs),
}

#[derive(Args)]
struct StatsRenderArgs {
    #[arg(long)]
    db: PathBuf,
    #[arg(long = "post-guid")]
    post_guid: String,
    #[arg(long = "min-confidence")]
    min_confidence: f64,
    #[arg(long = "min-ad-segment-separation-seconds")]
    min_ad_segment_separation_seconds: f64,
    #[arg(long = "enable-boundary-refinement", action = ArgAction::Set)]
    enable_boundary_refinement: bool,
    #[arg(long = "stats-debug", action = ArgAction::Set)]
    stats_debug: bool,
    #[arg(long = "log-path")]
    log_path: PathBuf,
    #[arg(long = "in-root")]
    in_root: PathBuf,
    #[arg(long = "srv-root")]
    srv_root: PathBuf,
}

#[derive(Args)]
struct FeedRenderArgs {
    #[arg(long)]
    db: PathBuf,
    #[arg(long = "feed-id")]
    feed_id: i64,
    #[arg(long = "base-url")]
    base_url: String,
    #[arg(long = "include-unprocessed")]
    include_unprocessed: bool,
    #[arg(long = "feed-token")]
    feed_token: Option<String>,
    #[arg(long = "feed-secret")]
    feed_secret: Option<String>,
}

#[derive(Args)]
struct FeedRenderAggregateArgs {
    #[arg(long)]
    db: PathBuf,
    #[arg(long = "user-id")]
    user_id: i64,
    #[arg(long = "base-url")]
    base_url: String,
    #[arg(long = "require-auth")]
    require_auth: bool,
    #[arg(long = "limit-per-feed")]
    limit_per_feed: usize,
    #[arg(long = "feed-token")]
    feed_token: Option<String>,
    #[arg(long = "feed-secret")]
    feed_secret: Option<String>,
}

#[derive(Args)]
struct FeedRefreshPlanArgs {
    #[arg(long)]
    db: PathBuf,
    #[arg(long = "feed-id")]
    feed_id: i64,
    #[arg(long = "feed-xml")]
    feed_xml: PathBuf,
    #[arg(long = "auto-whitelist-new-posts", action = ArgAction::Set)]
    auto_whitelist_new_posts: bool,
}

#[derive(Args)]
struct TranscriptCommand {
    #[command(subcommand)]
    command: TranscriptSubcommand,
}

#[derive(Subcommand)]
enum TranscriptSubcommand {
    NormalizeWordTimestamps(TranscriptNormalizeArgs),
    ExportWordTimestamps(TranscriptExportArgs),
    AdMerge(TranscriptAdMergeArgs),
    ProfanityWindows(TranscriptProfanityWindowsArgs),
}

#[derive(Args)]
struct TranscriptProfanityWindowsArgs {
    #[arg(long)]
    input: PathBuf,
}

#[derive(Args)]
struct TranscriptAdMergeArgs {
    #[arg(long)]
    db: PathBuf,
    #[arg(long = "post-guid")]
    post_guid: String,
    #[arg(long = "min-confidence")]
    min_confidence: f64,
    #[arg(long = "max-gap")]
    max_gap: f64,
    #[arg(long = "enable-boundary-refinement", action = ArgAction::Set)]
    enable_boundary_refinement: bool,
}

#[derive(Args)]
struct TranscriptNormalizeArgs {
    #[arg(long)]
    input: PathBuf,
    #[arg(long)]
    output: PathBuf,
}

#[derive(Args)]
struct TranscriptExportArgs {
    #[arg(long)]
    db: PathBuf,
    #[arg(long = "post-id")]
    post_id: i64,
}

#[derive(Args)]
struct ChaptersCommand {
    #[command(subcommand)]
    command: ChaptersSubcommand,
}

#[derive(Subcommand)]
enum ChaptersSubcommand {
    Read(ChaptersReadArgs),
    Detect(ChaptersDetectArgs),
    Write(ChaptersWriteArgs),
}

#[derive(Args)]
struct ChaptersReadArgs {
    #[arg(long)]
    audio: PathBuf,
}

#[derive(Args)]
struct ChaptersDetectArgs {
    #[arg(long)]
    audio: PathBuf,
    #[arg(long = "filter-strings-csv")]
    filter_strings_csv: String,
}

#[derive(Args)]
struct ChaptersWriteArgs {
    #[arg(long)]
    audio: PathBuf,
    #[arg(long = "chapters-json")]
    chapters_json: PathBuf,
    #[arg(long = "removed-windows-json")]
    removed_windows_json: PathBuf,
}

#[derive(Serialize)]
struct ProbeResponse {
    duration_ms: u64,
}

#[derive(Serialize)]
struct OkResponse {
    ok: bool,
}

#[derive(Serialize)]
struct SplitResponse {
    chunks: Vec<SplitChunk>,
}

#[derive(Serialize)]
struct SplitChunk {
    path: String,
    offset_ms: u64,
}

#[derive(Deserialize)]
struct WindowMs(u64, u64);

#[derive(Serialize)]
struct NormalizedWordSegment {
    sequence_num: i64,
    words: Vec<NormalizedWord>,
}

#[derive(Serialize)]
struct NormalizedWord {
    word: String,
    start: f64,
    end: f64,
    score: Option<f64>,
}

#[derive(Serialize)]
struct TranscriptExportResponse {
    transcript_word_timestamps: Value,
}

#[derive(Serialize)]
struct XmlResponse {
    xml: String,
}

struct FeedRow {
    id: i64,
    title: String,
    description: Option<String>,
    image_url: Option<String>,
    last_changed_at: Option<String>,
}

struct FeedRefreshFeedRow {
    id: i64,
    image_url: Option<String>,
}

struct FeedRefreshPostRow {
    id: i64,
    guid: String,
    download_url: String,
    title: String,
    description: Option<String>,
    processed_audio_path: Option<String>,
    release_date: Option<String>,
    duration: Option<i64>,
    image_url: Option<String>,
}

#[derive(Debug)]
struct ParsedFeedEntry {
    guid: String,
    title: String,
    description: String,
    download_url: String,
    release_date: Option<String>,
    duration: Option<i64>,
    image_url: Option<String>,
}

struct PostRow {
    feed_title: Option<String>,
    title: String,
    guid: String,
    processed_audio_path: Option<String>,
    description: Option<String>,
    release_date: Option<String>,
    duration: Option<i64>,
    image_url: Option<String>,
    chapter_data: Option<String>,
}

struct RssBuildArgs<'a> {
    title: &'a str,
    link: &'a str,
    description: &'a str,
    image_url: Option<&'a str>,
    image_title: &'a str,
    last_build_date: &'a str,
    base_url: &'a str,
    feed_token: Option<&'a str>,
    feed_secret: Option<&'a str>,
    posts: &'a [PostRow],
    prepend_feed_title: bool,
}

#[derive(Deserialize)]
struct ChapterPayload {
    title: String,
    start_time_ms: u32,
    end_time_ms: u32,
}

#[derive(Clone, Serialize)]
struct ChapterResponseItem {
    element_id: String,
    title: String,
    start_time_ms: u32,
    end_time_ms: u32,
}

#[derive(Serialize)]
struct ChaptersReadResponse {
    chapters: Vec<ChapterResponseItem>,
}

#[derive(Serialize)]
struct ChaptersDetectResponse {
    ad_segments: Vec<(f64, f64)>,
    chapters_to_keep: Vec<ChapterResponseItem>,
    chapters_to_remove: Vec<ChapterResponseItem>,
}

#[derive(Clone)]
struct StatsPostRow {
    id: i64,
    feed_id: i64,
    guid: String,
    title: String,
    download_url: String,
    unprocessed_audio_path: Option<String>,
    processed_audio_path: Option<String>,
    release_date: Option<String>,
    duration: Option<f64>,
    whitelisted: bool,
    download_count: Option<i64>,
    chapter_data: Option<String>,
    bleep_windows: Option<String>,
    refined_ad_boundaries: Option<String>,
}

struct StatsFeedRow {
    ad_detection_strategy: String,
    chapter_filter_strings: Option<String>,
}

#[derive(Clone)]
struct StatsTranscriptSegmentRow {
    id: i64,
    sequence_num: i64,
    start_time: f64,
    end_time: f64,
    text: String,
    speaker_label: Option<String>,
}

#[derive(Clone)]
struct StatsIdentificationRow {
    id: i64,
    transcript_segment_id: i64,
    label: String,
    confidence: Option<f64>,
    model_call_id: i64,
    model_call_status: String,
    segment_sequence_num: i64,
    segment_start_time: f64,
    segment_end_time: f64,
    segment_text: String,
}

#[derive(Clone)]
struct StatsAudioSegmentRow {
    id: i64,
    start_time: f64,
    end_time: f64,
    label: String,
    model_call_id: Option<i64>,
}

struct StatsModelCallRow {
    id: i64,
    model_name: String,
    status: String,
    first_segment_sequence_num: i64,
    last_segment_sequence_num: i64,
    timestamp: Option<String>,
    retry_attempts: i64,
    error_message: Option<String>,
    prompt: String,
    response: Option<String>,
}

struct StatsProcessingJobRow {
    id: String,
}

#[derive(Clone)]
struct StatsAdGroup {
    segments: Vec<StatsTranscriptSegmentRow>,
    identifications: Vec<StatsIdentificationRow>,
    start_time: f64,
    end_time: f64,
    confidence_avg: f64,
    keywords: Vec<String>,
}

#[derive(Clone)]
struct RefinedBoundaryRow {
    orig_start: f64,
    orig_end: f64,
    refined_start: f64,
    refined_end: f64,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error:#}");
        std::process::exit(1);
    }
}

fn run() -> Result<()> {
    let cli = Cli::parse();

    match cli.command {
        Commands::Audio(audio) => match audio.command {
            AudioSubcommand::Probe(args) => print_json(&probe_audio_path(&args.input)?),
            AudioSubcommand::Cut(args) => print_json(&cut_audio(args)?),
            AudioSubcommand::Bleep(args) => print_json(&bleep_audio(args)?),
            AudioSubcommand::Split(args) => print_json(&split_audio(args)?),
        },
        Commands::Feed(feed) => match feed.command {
            FeedSubcommand::Render(args) => print_json(&render_feed(args)?),
            FeedSubcommand::RenderAggregate(args) => print_json(&render_aggregate_feed(args)?),
            FeedSubcommand::RefreshPlan(args) => print_json(&plan_feed_refresh(args)?),
        },
        Commands::Jobs(jobs) => match jobs.command {
            JobsSubcommand::Active(args) => print_json(&render_jobs(args, true)?),
            JobsSubcommand::All(args) => print_json(&render_jobs(args, false)?),
            JobsSubcommand::Status(args) => print_json(&render_jobs_status(args)?),
        },
        Commands::Stats(stats) => match stats.command {
            StatsSubcommand::Render(args) => print_json(&render_stats(args)?),
        },
        Commands::Transcript(transcript) => match transcript.command {
            TranscriptSubcommand::NormalizeWordTimestamps(args) => {
                print_json(&normalize_word_timestamps(args)?)
            }
            TranscriptSubcommand::ExportWordTimestamps(args) => {
                print_json(&export_word_timestamps(args)?)
            }
            TranscriptSubcommand::AdMerge(args) => print_json(&run_transcript_ad_merge(args)?),
            TranscriptSubcommand::ProfanityWindows(args) => {
                print_json(&run_transcript_profanity_windows(args)?)
            }
        },
        Commands::Chapters(chapters) => match chapters.command {
            ChaptersSubcommand::Read(args) => print_json(&read_chapters(args)?),
            ChaptersSubcommand::Detect(args) => print_json(&detect_chapter_ads(args)?),
            ChaptersSubcommand::Write(args) => print_json(&write_chapters(args)?),
        },
    }
}

#[derive(Deserialize)]
struct ProfanityWord {
    word: Option<String>,
    start: Option<f64>,
    end: Option<f64>,
}

#[derive(Deserialize)]
struct ProfanityRequest {
    words: Vec<ProfanityWord>,
    profanity_terms: Vec<String>,
    pad_start_ms: i64,
    pad_end_ms: i64,
    merge_gap_ms: i64,
}

fn run_transcript_profanity_windows(args: TranscriptProfanityWindowsArgs) -> Result<Value> {
    let raw = std::fs::read_to_string(&args.input)
        .with_context(|| format!("failed to read profanity input {}", args.input.display()))?;
    let request: ProfanityRequest =
        serde_json::from_str(&raw).context("failed to parse profanity-windows input as JSON")?;

    static NORMALIZE_RE: OnceLock<Regex> = OnceLock::new();
    let normalize_re =
        NORMALIZE_RE.get_or_init(|| Regex::new(r"(^[^A-Za-z0-9']+)|([^A-Za-z0-9']+$)").unwrap());

    let terms: HashSet<String> = request
        .profanity_terms
        .into_iter()
        .map(|t| t.to_lowercase())
        .collect();

    let mut raw_windows: Vec<(i64, i64)> = Vec::new();
    for w in request.words {
        let (Some(text), Some(start), Some(end)) = (w.word, w.start, w.end) else {
            continue;
        };
        let normalized = normalize_re.replace_all(&text, "").to_lowercase();
        if normalized.is_empty() || !terms.contains(&normalized) {
            continue;
        }
        let start_ms = ((start * 1000.0).floor() as i64 - request.pad_start_ms).max(0);
        let end_ms = ((end * 1000.0).ceil() as i64 + request.pad_end_ms).max(start_ms + 1);
        raw_windows.push((start_ms, end_ms));
    }

    raw_windows.sort();
    let mut merged: Vec<(i64, i64)> = Vec::with_capacity(raw_windows.len());
    for (start, end) in raw_windows {
        if let Some(last) = merged.last_mut() {
            if start <= last.1 + request.merge_gap_ms {
                last.1 = last.1.max(end);
                continue;
            }
        }
        merged.push((start, end));
    }

    let windows: Vec<Value> = merged.into_iter().map(|(s, e)| json!([s, e])).collect();
    Ok(json!({ "windows_ms": windows }))
}

fn run_transcript_ad_merge(args: TranscriptAdMergeArgs) -> Result<Value> {
    let conn = open_readonly_sqlite(&args.db)?;
    let post = query_stats_post(&conn, &args.post_guid)?
        .ok_or_else(|| anyhow!("post not found for guid {}", args.post_guid))?;
    let transcript_segments = query_stats_transcript_segments(&conn, post.id)?;
    let audio_segments = query_stats_audio_segments(&conn, post.id)?;
    let identifications = query_stats_identifications(&conn, post.id)?;
    let ad_blocks = build_stats_ad_blocks(
        &post,
        &transcript_segments,
        &audio_segments,
        &identifications,
        args.min_confidence,
        args.max_gap,
        args.enable_boundary_refinement,
    );
    let ad_segments: Vec<Value> = ad_blocks
        .iter()
        .map(|(start, end)| json!([start, end]))
        .collect();
    Ok(json!({ "ad_segments": ad_segments }))
}

fn render_stats(args: StatsRenderArgs) -> Result<Value> {
    let conn = open_readonly_sqlite(&args.db)?;
    let post = query_stats_post(&conn, &args.post_guid)?
        .ok_or_else(|| anyhow!("post not found for guid {}", args.post_guid))?;
    let feed = query_stats_feed(&conn, post.feed_id)?;
    let model_calls = query_stats_model_calls(&conn, post.id)?;
    let recent_jobs = query_stats_processing_jobs(&conn, &post.guid)?;
    let transcript_segments = query_stats_transcript_segments(&conn, post.id)?;
    let audio_segments = query_stats_audio_segments(&conn, post.id)?;
    let identifications = query_stats_identifications(&conn, post.id)?;

    let ad_detection_strategy = feed
        .as_ref()
        .map(|feed| feed.ad_detection_strategy.as_str())
        .unwrap_or("llm");
    let (model_call_statuses, model_types) = count_stats_model_calls(&model_calls);
    let identifications_by_segment = group_stats_identifications_by_segment(&identifications);
    let (content_segments, ad_segments_count) =
        count_stats_primary_labels(&transcript_segments, &identifications_by_segment);
    let refined_windows = parse_refined_windows_json(post.refined_ad_boundaries.as_deref());
    let bleep_windows =
        parse_time_windows_json(post.bleep_windows.as_deref(), "start_time", "end_time");

    let mut segment_mixed_by_id: HashMap<i64, bool> = HashMap::new();
    let transcript_segments_data: Vec<Value> = transcript_segments
        .iter()
        .map(|segment| {
            let segment_identifications = identifications_by_segment
                .get(&segment.id)
                .cloned()
                .unwrap_or_default();
            let has_ad_label = segment_identifications
                .iter()
                .any(|ident| ident.label == "ad");
            let mixed = has_ad_label
                && is_mixed_segment(segment.start_time, segment.end_time, &refined_windows);
            segment_mixed_by_id.insert(segment.id, mixed);
            json!({
                "id": segment.id,
                "sequence_num": segment.sequence_num,
                "start_time": round_to(segment.start_time, 1),
                "end_time": round_to(segment.end_time, 1),
                "speaker_label": segment.speaker_label,
                "text": segment.text,
                "primary_label": if has_ad_label { "ad" } else { "content" },
                "mixed": mixed,
                "identifications": segment_identifications.iter().map(|ident| json!({
                    "id": ident.id,
                    "label": ident.label,
                    "confidence": ident.confidence.map(|value| round_to(value, 2)),
                    "model_call_id": ident.model_call_id,
                })).collect::<Vec<_>>(),
            })
        })
        .collect();

    let ad_blocks = build_stats_ad_blocks(
        &post,
        &transcript_segments,
        &audio_segments,
        &identifications,
        args.min_confidence,
        args.min_ad_segment_separation_seconds,
        args.enable_boundary_refinement,
    );
    let ad_time_seconds: f64 = ad_blocks
        .iter()
        .filter(|(start, end)| end > start)
        .map(|(start, end)| end - start)
        .sum();
    let original_duration_seconds = resolve_original_duration_seconds(
        post.duration,
        &transcript_segments,
        &bleep_windows,
        ad_time_seconds,
    );
    let ad_percentage = if original_duration_seconds > 0.0 {
        ad_time_seconds / original_duration_seconds * 100.0
    } else {
        0.0
    };
    let bleep_time_seconds: f64 = bleep_windows
        .iter()
        .filter(|(start, end)| end > start)
        .map(|(start, end)| end - start)
        .sum();
    let bleep_percentage = if original_duration_seconds > 0.0 {
        bleep_time_seconds / original_duration_seconds * 100.0
    } else {
        0.0
    };
    let edited_duration_seconds = (original_duration_seconds - ad_time_seconds).max(0.0);

    let chapters = build_stats_chapters(&post, feed.as_ref(), ad_detection_strategy)?;
    let related_logs = build_related_logs_for_stats(&args.log_path, &post, &recent_jobs);

    let mut stats = json!({
        "post": {
            "guid": post.guid,
            "title": post.title,
            "duration": post.duration,
            "release_date": post.release_date,
            "whitelisted": post.whitelisted,
            "has_processed_audio": post.processed_audio_path.is_some(),
            "download_count": post.download_count,
        },
        "ad_detection_strategy": ad_detection_strategy,
        "processing_stats": {
            "total_segments": transcript_segments.len(),
            "total_model_calls": model_calls.len(),
            "total_identifications": identifications.len(),
            "audio_segments_count": audio_segments.len(),
            "content_segments": content_segments,
            "ad_segments_count": ad_segments_count,
            "ad_percentage": round_to(ad_percentage, 1),
            "estimated_ad_time_seconds": round_to(ad_time_seconds, 1),
            "original_duration_seconds": round_to(original_duration_seconds, 1),
            "edited_duration_seconds": round_to(edited_duration_seconds, 1),
            "ad_blocks": ad_blocks.iter().map(|(start, end)| json!({
                "start_time": round_to(*start, 1),
                "end_time": round_to(*end, 1),
            })).collect::<Vec<_>>(),
            "edited_ad_markers": build_edited_timeline_ad_markers(&ad_blocks),
            "has_bleep_windows": !bleep_windows.is_empty(),
            "bleeped_time_seconds": round_to(bleep_time_seconds, 1),
            "bleeped_percentage": round_to(bleep_percentage, 1),
            "bleep_windows": bleep_windows.iter().map(|(start, end)| json!({
                "start_time": round_to(*start, 3),
                "end_time": round_to(*end, 3),
            })).collect::<Vec<_>>(),
            "edited_bleep_windows": build_edited_timeline_bleep_windows(&bleep_windows, &ad_blocks),
            "speaker_breakdown": build_stats_speaker_breakdown(&transcript_segments),
            "model_call_statuses": model_call_statuses,
            "model_types": model_types,
        },
        "model_calls": model_calls.iter().map(|call| {
            let recorded_attempts = call.retry_attempts.max(0);
            json!({
                "id": call.id,
                "model_name": call.model_name,
                "status": call.status,
                "segment_range": format!("{}-{}", call.first_segment_sequence_num, call.last_segment_sequence_num),
                "first_segment_sequence_num": call.first_segment_sequence_num,
                "last_segment_sequence_num": call.last_segment_sequence_num,
                "timestamp": call.timestamp,
                "retry_attempts": recorded_attempts,
                "retry_count": (recorded_attempts - 1).max(0),
                "error_message": call.error_message,
                "prompt": call.prompt,
                "response": call.response,
            })
        }).collect::<Vec<_>>(),
        "transcript_segments": transcript_segments_data,
        "audio_segments": audio_segments.iter().map(|segment| json!({
            "id": segment.id,
            "start_time": round_to(segment.start_time, 1),
            "end_time": round_to(segment.end_time, 1),
            "label": segment.label,
            "model_call_id": segment.model_call_id,
        })).collect::<Vec<_>>(),
        "identifications": identifications.iter().map(|ident| json!({
            "id": ident.id,
            "transcript_segment_id": ident.transcript_segment_id,
            "label": ident.label,
            "confidence": ident.confidence.map(|value| round_to(value, 2)),
            "model_call_id": ident.model_call_id,
            "segment_sequence_num": ident.segment_sequence_num,
            "segment_start_time": round_to(ident.segment_start_time, 1),
            "segment_end_time": round_to(ident.segment_end_time, 1),
            "segment_text": ident.segment_text,
            "mixed": *segment_mixed_by_id.get(&ident.transcript_segment_id).unwrap_or(&false),
        })).collect::<Vec<_>>(),
        "related_logs": related_logs,
        "chapters": chapters,
    });

    if args.stats_debug {
        stats["debug_info"] = json!({
            "post_id": post.id,
            "feed_id": post.feed_id,
            "guid": post.guid,
            "download_url": post.download_url,
            "download_count": post.download_count,
            "has_processed_audio": post.processed_audio_path.is_some(),
            "has_unprocessed_audio": post.unprocessed_audio_path.is_some(),
            "processed_audio": build_file_debug(post.processed_audio_path.as_deref()),
            "unprocessed_audio": build_file_debug(post.unprocessed_audio_path.as_deref()),
            "processed_audio_path_candidates": [],
            "processing_roots": {
                "in_root": args.in_root.to_string_lossy().to_string(),
                "srv_root": args.srv_root.to_string_lossy().to_string(),
            },
            "record_counts": {
                "transcript_segments": transcript_segments.len(),
                "audio_segments": audio_segments.len(),
                "model_calls": model_calls.len(),
                "identifications": identifications.len(),
            },
        });
    }

    Ok(json!({ "stats": stats }))
}

fn render_jobs(args: JobsListArgs, active_only: bool) -> Result<Value> {
    let conn = open_readonly_sqlite(&args.db)?;
    let limit = args.limit.clamp(1, 1000);
    let status_filter = if active_only {
        "WHERE processing_job.status IN ('pending', 'running')"
    } else {
        ""
    };
    let sql = format!(
        "SELECT
            processing_job.id,
            processing_job.post_guid,
            post.title,
            feed.title,
            processing_job.status,
            CASE
                WHEN processing_job.status = 'running' THEN 2
                WHEN processing_job.status = 'pending' THEN 1
                ELSE 0
            END AS priority,
            processing_job.current_step,
            processing_job.step_name,
            processing_job.total_steps,
            processing_job.progress_percentage,
            processing_job.created_at,
            processing_job.started_at,
            processing_job.completed_at,
            processing_job.error_message,
            processing_job.stage_history
         FROM processing_job
         LEFT JOIN post ON processing_job.post_guid = post.guid
         LEFT JOIN feed ON post.feed_id = feed.id
         {status_filter}
         ORDER BY priority DESC, processing_job.created_at DESC
         LIMIT ?1"
    );
    let mut stmt = conn.prepare(&sql)?;
    let rows = stmt.query_map([limit], |row| {
        // SQLAlchemy stores the JSON column as TEXT; parse it back here so
        // the API surface matches the Python `list_active_jobs` serializer.
        // Tolerate legacy rows (NULL or invalid JSON) by emitting an empty
        // array rather than failing the entire job listing.
        let stage_history_raw: Option<String> = row.get(14)?;
        let stage_history: Value = stage_history_raw
            .and_then(|raw| serde_json::from_str::<Value>(&raw).ok())
            .filter(|value| value.is_array())
            .unwrap_or_else(|| Value::Array(Vec::new()));
        Ok(json!({
            "job_id": row.get::<_, String>(0)?,
            "post_guid": row.get::<_, String>(1)?,
            "post_title": row.get::<_, Option<String>>(2)?,
            "feed_title": row.get::<_, Option<String>>(3)?,
            "status": row.get::<_, String>(4)?,
            "priority": row.get::<_, i64>(5)?,
            "step": row.get::<_, Option<i64>>(6)?,
            "step_name": row.get::<_, Option<String>>(7)?,
            "total_steps": row.get::<_, Option<i64>>(8)?,
            "progress_percentage": row.get::<_, Option<f64>>(9)?,
            "created_at": row.get::<_, Option<String>>(10)?.map(|value| sqlite_datetime_to_iso(&value)),
            "started_at": row.get::<_, Option<String>>(11)?.map(|value| sqlite_datetime_to_iso(&value)),
            "completed_at": row.get::<_, Option<String>>(12)?.map(|value| sqlite_datetime_to_iso(&value)),
            "error_message": row.get::<_, Option<String>>(13)?,
            "stage_history": stage_history,
        }))
    })?;
    let jobs = rows.collect::<std::result::Result<Vec<_>, _>>()?;
    Ok(json!({ "jobs": jobs }))
}

const JOBS_MANAGER_SINGLETON_RUN_ID: &str = "jobs-manager-singleton";

// Read-only equivalent of `build_run_status_snapshot` in
// app/jobs_manager_run_service.py: load the singleton run row, aggregate the
// processing_job statuses scoped to that run, and shape the response the
// same way the Python serializer does so the Flask route can transparently
// fall through to either implementation.
fn render_jobs_status(args: JobsStatusArgs) -> Result<Value> {
    let conn = open_readonly_sqlite(&args.db)?;

    let run = conn.query_row(
        "SELECT id, status, trigger, started_at, completed_at, updated_at,
                counters_reset_at, context_json
         FROM jobs_manager_run WHERE id = ?1",
        [JOBS_MANAGER_SINGLETON_RUN_ID],
        |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, Option<String>>(1)?,
                row.get::<_, Option<String>>(2)?,
                row.get::<_, Option<String>>(3)?,
                row.get::<_, Option<String>>(4)?,
                row.get::<_, Option<String>>(5)?,
                row.get::<_, Option<String>>(6)?,
                row.get::<_, Option<String>>(7)?,
            ))
        },
    );

    // `prior_status` is intentionally discarded: Python computes status from
    // the live counts, not from whatever was persisted on the run row.
    let (
        run_id,
        _prior_status,
        trigger,
        started_at,
        completed_at,
        updated_at,
        counters_reset_at,
        context_json_raw,
    ) = match run {
        Ok(values) => values,
        // The Python jobs-manager-status route returns `{"run": null}` when
        // the singleton row hasn't been created yet; mirror that shape so
        // callers can pass our payload through unchanged.
        Err(rusqlite::Error::QueryReturnedNoRows) => return Ok(json!({ "run": Value::Null })),
        Err(err) => return Err(err.into()),
    };

    let mut count_query = String::from(
        "SELECT status, COUNT(id) FROM processing_job WHERE jobs_manager_run_id = ?1",
    );
    let mut params: Vec<rusqlite::types::Value> = vec![run_id.clone().into()];
    if let Some(cutoff) = counters_reset_at.as_deref() {
        count_query.push_str(" AND created_at >= ?2");
        params.push(cutoff.to_string().into());
    }
    count_query.push_str(" GROUP BY status");

    let mut stmt = conn.prepare(&count_query)?;
    let mut counts: HashMap<String, i64> = HashMap::new();
    let rows = stmt.query_map(rusqlite::params_from_iter(params.iter()), |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?))
    })?;
    for entry in rows {
        let (status, count) = entry?;
        counts.insert(status, count);
    }

    let queued =
        counts.get("pending").copied().unwrap_or(0) + counts.get("queued").copied().unwrap_or(0);
    let running = counts.get("running").copied().unwrap_or(0);
    let completed = counts.get("completed").copied().unwrap_or(0);
    let failed =
        counts.get("failed").copied().unwrap_or(0) + counts.get("cancelled").copied().unwrap_or(0);
    let skipped = counts.get("skipped").copied().unwrap_or(0);
    let total_jobs: i64 = counts.values().sum();
    let has_active_work = (queued + running) > 0;

    let status = if has_active_work {
        if running > 0 {
            "running"
        } else {
            "pending"
        }
        .to_string()
    } else {
        // Matches Python: idle manager reports "pending".
        "pending".to_string()
    };

    let progress_percentage = if total_jobs > 0 {
        let pct = (f64::from((completed + skipped) as i32) / f64::from(total_jobs.max(1) as i32))
            * 100.0;
        (pct * 100.0).round() / 100.0
    } else {
        0.0
    };

    let context_value: Value = context_json_raw
        .and_then(|raw| serde_json::from_str::<Value>(&raw).ok())
        .unwrap_or(Value::Null);

    Ok(json!({
        "run": {
            "id": run_id,
            "status": status,
            "trigger": trigger,
            "started_at": started_at.map(|value| sqlite_datetime_to_iso(&value)),
            "completed_at": completed_at.map(|value| sqlite_datetime_to_iso(&value)),
            "updated_at": updated_at.map(|value| sqlite_datetime_to_iso(&value)),
            "total_jobs": total_jobs,
            "queued_jobs": queued,
            "running_jobs": running,
            "completed_jobs": completed,
            "failed_jobs": failed,
            "skipped_jobs": skipped,
            "context": context_value,
            "counters_reset_at": counters_reset_at.map(|value| sqlite_datetime_to_iso(&value)),
            "progress_percentage": progress_percentage,
        }
    }))
}

fn query_stats_post(conn: &Connection, guid: &str) -> Result<Option<StatsPostRow>> {
    let mut stmt = conn.prepare(
        "SELECT id, feed_id, guid, title, download_url, unprocessed_audio_path, processed_audio_path,
                release_date, duration, whitelisted, download_count, chapter_data,
                bleep_windows, refined_ad_boundaries
         FROM post WHERE guid = ?1 LIMIT 1",
    )?;
    let mut rows = stmt.query([guid])?;
    if let Some(row) = rows.next()? {
        Ok(Some(StatsPostRow {
            id: row.get(0)?,
            feed_id: row.get(1)?,
            guid: row.get(2)?,
            title: row.get(3)?,
            download_url: row.get(4)?,
            unprocessed_audio_path: row.get(5)?,
            processed_audio_path: row.get(6)?,
            release_date: row
                .get::<_, Option<String>>(7)?
                .map(|value| sqlite_datetime_to_iso(&value)),
            duration: get_duration_f64(row, 8)?,
            whitelisted: row.get(9)?,
            download_count: row.get(10)?,
            chapter_data: row.get(11)?,
            bleep_windows: row.get(12)?,
            refined_ad_boundaries: row.get(13)?,
        }))
    } else {
        Ok(None)
    }
}

fn query_stats_feed(conn: &Connection, feed_id: i64) -> Result<Option<StatsFeedRow>> {
    let mut stmt = conn
        .prepare("SELECT ad_detection_strategy, chapter_filter_strings FROM feed WHERE id = ?1")?;
    let mut rows = stmt.query([feed_id])?;
    if let Some(row) = rows.next()? {
        Ok(Some(StatsFeedRow {
            ad_detection_strategy: row
                .get::<_, Option<String>>(0)?
                .unwrap_or_else(|| "llm".to_string()),
            chapter_filter_strings: row.get(1)?,
        }))
    } else {
        Ok(None)
    }
}

fn query_stats_model_calls(conn: &Connection, post_id: i64) -> Result<Vec<StatsModelCallRow>> {
    let mut stmt = conn.prepare(
        "SELECT id, model_name, status, first_segment_sequence_num, last_segment_sequence_num,
                timestamp, retry_attempts, error_message, prompt, response
         FROM model_call WHERE post_id = ?1
         ORDER BY model_name, first_segment_sequence_num",
    )?;
    let rows = stmt.query_map([post_id], |row| {
        Ok(StatsModelCallRow {
            id: row.get(0)?,
            model_name: row.get(1)?,
            status: row.get(2)?,
            first_segment_sequence_num: row.get(3)?,
            last_segment_sequence_num: row.get(4)?,
            timestamp: row
                .get::<_, Option<String>>(5)?
                .map(|value| sqlite_datetime_to_iso(&value)),
            retry_attempts: row.get::<_, Option<i64>>(6)?.unwrap_or(0),
            error_message: row.get(7)?,
            prompt: row.get(8)?,
            response: row.get(9)?,
        })
    })?;
    Ok(rows.collect::<std::result::Result<Vec<_>, _>>()?)
}

fn query_stats_processing_jobs(
    conn: &Connection,
    guid: &str,
) -> Result<Vec<StatsProcessingJobRow>> {
    let mut stmt = conn.prepare(
        "SELECT id FROM processing_job WHERE post_guid = ?1 ORDER BY created_at DESC LIMIT 3",
    )?;
    let rows = stmt.query_map([guid], |row| Ok(StatsProcessingJobRow { id: row.get(0)? }))?;
    Ok(rows.collect::<std::result::Result<Vec<_>, _>>()?)
}

fn query_stats_transcript_segments(
    conn: &Connection,
    post_id: i64,
) -> Result<Vec<StatsTranscriptSegmentRow>> {
    let mut stmt = conn.prepare(
        "SELECT id, sequence_num, start_time, end_time, text, speaker_label
         FROM transcript_segment WHERE post_id = ?1 ORDER BY sequence_num",
    )?;
    let rows = stmt.query_map([post_id], |row| {
        Ok(StatsTranscriptSegmentRow {
            id: row.get(0)?,
            sequence_num: row.get(1)?,
            start_time: row.get(2)?,
            end_time: row.get(3)?,
            text: row.get(4)?,
            speaker_label: row.get(5)?,
        })
    })?;
    Ok(rows.collect::<std::result::Result<Vec<_>, _>>()?)
}

fn query_stats_audio_segments(
    conn: &Connection,
    post_id: i64,
) -> Result<Vec<StatsAudioSegmentRow>> {
    let mut stmt = conn.prepare(
        "SELECT id, start_time, end_time, label, model_call_id
         FROM audio_segment WHERE post_id = ?1 ORDER BY start_time",
    )?;
    let rows = stmt.query_map([post_id], |row| {
        Ok(StatsAudioSegmentRow {
            id: row.get(0)?,
            start_time: row.get(1)?,
            end_time: row.get(2)?,
            label: row.get(3)?,
            model_call_id: row.get(4)?,
        })
    })?;
    Ok(rows.collect::<std::result::Result<Vec<_>, _>>()?)
}

fn query_stats_identifications(
    conn: &Connection,
    post_id: i64,
) -> Result<Vec<StatsIdentificationRow>> {
    let mut stmt = conn.prepare(
        "SELECT identification.id, identification.transcript_segment_id, identification.label,
                identification.confidence, identification.model_call_id, model_call.status,
                transcript_segment.sequence_num, transcript_segment.start_time,
                transcript_segment.end_time, transcript_segment.text
         FROM identification
         JOIN transcript_segment ON identification.transcript_segment_id = transcript_segment.id
         JOIN model_call ON identification.model_call_id = model_call.id
         WHERE transcript_segment.post_id = ?1
         ORDER BY transcript_segment.sequence_num",
    )?;
    let rows = stmt.query_map([post_id], |row| {
        Ok(StatsIdentificationRow {
            id: row.get(0)?,
            transcript_segment_id: row.get(1)?,
            label: row.get(2)?,
            confidence: row.get(3)?,
            model_call_id: row.get(4)?,
            model_call_status: row.get(5)?,
            segment_sequence_num: row.get(6)?,
            segment_start_time: row.get(7)?,
            segment_end_time: row.get(8)?,
            segment_text: row.get(9)?,
        })
    })?;
    Ok(rows.collect::<std::result::Result<Vec<_>, _>>()?)
}

// SQLite INTEGER columns can hold real values due to dynamic typing. Read as f64
// to avoid rusqlite type mismatch errors.
fn get_duration_f64(row: &rusqlite::Row<'_>, idx: usize) -> rusqlite::Result<Option<f64>> {
    row.get::<_, Option<f64>>(idx)
}

fn get_duration_seconds(row: &rusqlite::Row<'_>, idx: usize) -> rusqlite::Result<Option<i64>> {
    Ok(get_duration_f64(row, idx)?.map(|v| v as i64))
}

fn round_to(value: f64, places: i32) -> f64 {
    let factor = 10_f64.powi(places);
    (value * factor).round() / factor
}

fn sqlite_datetime_to_iso(value: &str) -> String {
    let iso = if value.contains('T') {
        value.to_string()
    } else {
        value.replace(' ', "T")
    };
    iso.strip_suffix(".000000").unwrap_or(&iso).to_string()
}

fn count_stats_model_calls(
    model_calls: &[StatsModelCallRow],
) -> (HashMap<String, i64>, HashMap<String, i64>) {
    let mut statuses = HashMap::new();
    let mut types = HashMap::new();
    for call in model_calls {
        *statuses.entry(call.status.clone()).or_insert(0) += 1;
        *types.entry(call.model_name.clone()).or_insert(0) += 1;
    }
    (statuses, types)
}

fn group_stats_identifications_by_segment(
    identifications: &[StatsIdentificationRow],
) -> HashMap<i64, Vec<StatsIdentificationRow>> {
    let mut grouped: HashMap<i64, Vec<StatsIdentificationRow>> = HashMap::new();
    for ident in identifications {
        grouped
            .entry(ident.transcript_segment_id)
            .or_default()
            .push(ident.clone());
    }
    grouped
}

fn count_stats_primary_labels(
    segments: &[StatsTranscriptSegmentRow],
    grouped: &HashMap<i64, Vec<StatsIdentificationRow>>,
) -> (usize, usize) {
    let mut content = 0;
    let mut ads = 0;
    for segment in segments {
        if grouped
            .get(&segment.id)
            .map(|items| items.iter().any(|ident| ident.label == "ad"))
            .unwrap_or(false)
        {
            ads += 1;
        } else {
            content += 1;
        }
    }
    (content, ads)
}

fn parse_refined_windows_json(raw: Option<&str>) -> Vec<(f64, f64)> {
    parse_time_windows_json(raw, "refined_start", "refined_end")
}

fn parse_time_windows_json(raw: Option<&str>, start_key: &str, end_key: &str) -> Vec<(f64, f64)> {
    let Some(raw) = raw else {
        return Vec::new();
    };
    let Ok(Value::Array(items)) = serde_json::from_str::<Value>(raw) else {
        return Vec::new();
    };
    items
        .iter()
        .filter_map(|item| {
            let object = item.as_object()?;
            let start = value_to_f64(object.get(start_key)?)?;
            let end = value_to_f64(object.get(end_key)?)?;
            (end > start).then_some((start, end))
        })
        .collect()
}

fn is_mixed_segment(seg_start: f64, seg_end: f64, refined_windows: &[(f64, f64)]) -> bool {
    refined_windows.iter().any(|(win_start, win_end)| {
        let overlaps = seg_start <= *win_end && seg_end >= *win_start;
        let fully_contained = seg_start >= *win_start && seg_end <= *win_end;
        overlaps && !fully_contained
    })
}

fn build_stats_speaker_breakdown(segments: &[StatsTranscriptSegmentRow]) -> Vec<Value> {
    let mut totals: HashMap<Option<String>, (f64, i64)> = HashMap::new();
    let mut total_time = 0.0;
    for segment in segments {
        let duration = segment.end_time - segment.start_time;
        if duration <= 0.0 {
            continue;
        }
        let label = segment.speaker_label.as_ref().and_then(|value| {
            let trimmed = value.trim();
            (!trimmed.is_empty()).then(|| trimmed.to_string())
        });
        let entry = totals.entry(label).or_insert((0.0, 0));
        entry.0 += duration;
        entry.1 += 1;
        total_time += duration;
    }
    let mut entries: Vec<_> = totals.into_iter().collect();
    entries.sort_by(|(label_a, (time_a, _)), (label_b, (time_b, _))| {
        time_b
            .partial_cmp(time_a)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| label_a.is_none().cmp(&label_b.is_none()))
            .then_with(|| label_a.cmp(label_b))
    });
    entries
        .into_iter()
        .map(|(label, (time, count))| {
            json!({
                "speaker_label": label,
                "speaking_time_seconds": round_to(time, 1),
                "speaking_percentage": round_to(if total_time > 0.0 { time / total_time * 100.0 } else { 0.0 }, 1),
                "segment_count": count,
            })
        })
        .collect()
}

fn build_stats_ad_blocks(
    post: &StatsPostRow,
    transcript_segments: &[StatsTranscriptSegmentRow],
    audio_segments: &[StatsAudioSegmentRow],
    identifications: &[StatsIdentificationRow],
    min_confidence: f64,
    max_gap: f64,
    enable_boundary_refinement: bool,
) -> Vec<(f64, f64)> {
    let segment_by_id: HashMap<i64, StatsTranscriptSegmentRow> = transcript_segments
        .iter()
        .map(|segment| (segment.id, segment.clone()))
        .collect();
    let ad_identifications: Vec<StatsIdentificationRow> = identifications
        .iter()
        .filter(|ident| ident.label == "ad")
        .filter(|ident| ident.confidence.unwrap_or(0.0) >= min_confidence)
        .filter(|ident| ident.model_call_status == "success")
        .cloned()
        .collect();
    let mut ad_segments: Vec<StatsTranscriptSegmentRow> = ad_identifications
        .iter()
        .filter_map(|ident| segment_by_id.get(&ident.transcript_segment_id).cloned())
        .collect();
    ad_segments.sort_by(|a, b| {
        a.start_time
            .partial_cmp(&b.start_time)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    if ad_segments.is_empty() {
        return Vec::new();
    }

    let groups = merge_stats_ad_segments(&ad_segments, &ad_identifications, max_gap);
    let refined_boundaries = if enable_boundary_refinement {
        parse_refined_boundaries_full(post.refined_ad_boundaries.as_deref())
    } else {
        Vec::new()
    };
    let mut ad_windows: Vec<(f64, f64)> = groups
        .iter()
        .map(|group| cut_window_for_stats_ad_group(group, &refined_boundaries))
        .collect();
    let bridgeable_audio = extract_audio_windows(audio_segments, false);
    if !bridgeable_audio.is_empty() {
        ad_windows = bridge_ad_windows_with_audio(&ad_windows, &bridgeable_audio);
    }
    let edge_audio = extract_audio_windows(audio_segments, true);
    if !edge_audio.is_empty()
        && !has_transcript_content_before_first_ad(
            transcript_segments,
            &ad_windows,
            &ad_identifications,
        )
    {
        ad_windows = expand_episode_edge_ad_windows_with_audio(&ad_windows, &edge_audio);
    }
    ad_windows.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    ad_windows
}

fn merge_stats_ad_segments(
    segments: &[StatsTranscriptSegmentRow],
    identifications: &[StatsIdentificationRow],
    max_gap: f64,
) -> Vec<StatsAdGroup> {
    let mut groups = Vec::new();
    let mut current = Vec::new();
    for segment in segments {
        if current
            .last()
            .map(|last: &StatsTranscriptSegmentRow| segment.start_time - last.end_time <= max_gap)
            .unwrap_or(true)
        {
            current.push(segment.clone());
        } else {
            groups.push(create_stats_ad_group(&current, identifications));
            current = vec![segment.clone()];
        }
    }
    if !current.is_empty() {
        groups.push(create_stats_ad_group(&current, identifications));
    }

    let refined = refine_stats_ad_groups(groups);
    refined
        .into_iter()
        .filter(is_valid_stats_ad_group)
        .collect()
}

fn create_stats_ad_group(
    segments: &[StatsTranscriptSegmentRow],
    identifications: &[StatsIdentificationRow],
) -> StatsAdGroup {
    let segment_ids: HashSet<i64> = segments.iter().map(|segment| segment.id).collect();
    let ids: Vec<_> = identifications
        .iter()
        .filter(|ident| segment_ids.contains(&ident.transcript_segment_id))
        .cloned()
        .collect();
    let confidence_avg = if ids.is_empty() {
        0.0
    } else {
        ids.iter()
            .map(|ident| ident.confidence.unwrap_or(0.0))
            .sum::<f64>()
            / ids.len() as f64
    };
    StatsAdGroup {
        segments: segments.to_vec(),
        identifications: ids,
        start_time: segments
            .first()
            .map(|segment| segment.start_time)
            .unwrap_or(0.0),
        end_time: segments
            .last()
            .map(|segment| segment.end_time)
            .unwrap_or(0.0),
        confidence_avg,
        keywords: extract_stats_keywords(segments),
    }
}

fn extract_stats_keywords(segments: &[StatsTranscriptSegmentRow]) -> Vec<String> {
    static URL_RE: OnceLock<Regex> = OnceLock::new();
    static PROMO_RE: OnceLock<Regex> = OnceLock::new();
    static PHONE_RE: OnceLock<Regex> = OnceLock::new();
    static BRAND_RE: OnceLock<Regex> = OnceLock::new();

    let text = segments
        .iter()
        .map(|segment| segment.text.as_str())
        .collect::<Vec<_>>()
        .join(" ");
    let lower = text.to_lowercase();
    let mut keywords = HashSet::new();
    let url_re =
        URL_RE.get_or_init(|| Regex::new(r"\b([a-z0-9\-\.]+\.(?:com|net|org|io))\b").unwrap());
    for capture in url_re.captures_iter(&lower) {
        keywords.insert(capture[1].to_string());
    }
    let promo_re = PROMO_RE.get_or_init(|| Regex::new(r"\b(code|promo|save)\s+\w+\b").unwrap());
    for capture in promo_re.captures_iter(&lower) {
        keywords.insert(capture[1].to_string());
    }
    let phone_re = PHONE_RE.get_or_init(|| Regex::new(r"\b\d{3}[ -]?\d{3}[ -]?\d{4}\b").unwrap());
    if phone_re.is_match(&lower) {
        keywords.insert("phone".to_string());
    }
    let mut counts: HashMap<String, usize> = HashMap::new();
    let brand_re = BRAND_RE.get_or_init(|| Regex::new(r"\b[A-Z][a-z]+\b").unwrap());
    for capture in brand_re.captures_iter(&text) {
        let word = capture[0].to_string();
        if word.len() > 3 {
            *counts.entry(word).or_insert(0) += 1;
        }
    }
    for (word, count) in counts {
        if count >= 2 {
            keywords.insert(word.to_lowercase());
        }
    }
    keywords.into_iter().collect()
}

fn refine_stats_ad_groups(groups: Vec<StatsAdGroup>) -> Vec<StatsAdGroup> {
    if groups.len() <= 1 {
        return groups;
    }
    let mut refined = Vec::new();
    let mut i = 0;
    while i < groups.len() {
        let current = &groups[i];
        if i + 1 < groups.len() {
            let next = &groups[i + 1];
            let gap = next.start_time - current.end_time;
            if gap <= 12.0 && should_merge_stats_ad_groups(current, next) {
                let mut segments = current.segments.clone();
                segments.extend(next.segments.clone());
                let mut ids = current.identifications.clone();
                ids.extend(next.identifications.clone());
                let mut keywords: HashSet<String> = current.keywords.iter().cloned().collect();
                keywords.extend(next.keywords.iter().cloned());
                refined.push(StatsAdGroup {
                    segments,
                    identifications: ids,
                    start_time: current.start_time,
                    end_time: next.end_time,
                    confidence_avg: (current.confidence_avg + next.confidence_avg) / 2.0,
                    keywords: keywords.into_iter().collect(),
                });
                i += 2;
            } else {
                refined.push(current.clone());
                i += 1;
            }
        } else {
            refined.push(current.clone());
            i += 1;
        }
    }
    refined
}

fn should_merge_stats_ad_groups(a: &StatsAdGroup, b: &StatsAdGroup) -> bool {
    if a.confidence_avg >= 0.9 && b.confidence_avg >= 0.9 {
        return true;
    }
    let a_keywords: HashSet<_> = a.keywords.iter().collect();
    if b.keywords
        .iter()
        .any(|keyword| a_keywords.contains(keyword))
    {
        return true;
    }
    let gap = b.start_time - a.end_time;
    gap <= 10.0 && a.confidence_avg >= 0.8 && b.confidence_avg >= 0.8
}

fn is_valid_stats_ad_group(group: &StatsAdGroup) -> bool {
    let duration = group.end_time - group.start_time;
    if duration > 180.0 && group.keywords.is_empty() && group.confidence_avg < 0.9 {
        return false;
    }
    if group.segments.len() < 2 || duration <= 10.0 {
        return !group.keywords.is_empty() || group.confidence_avg >= 0.9;
    }
    true
}

fn cut_window_for_stats_ad_group(
    group: &StatsAdGroup,
    refined: &[RefinedBoundaryRow],
) -> (f64, f64) {
    let blocks = atomic_ad_blocks_for_group(group);
    if blocks.is_empty() {
        return (group.start_time, group.end_time);
    }
    let projected: Vec<(f64, f64)> = blocks
        .into_iter()
        .map(|block| project_atomic_block(block, refined))
        .collect();
    (
        projected
            .iter()
            .map(|item| item.0)
            .fold(f64::INFINITY, f64::min),
        projected
            .iter()
            .map(|item| item.1)
            .fold(f64::NEG_INFINITY, f64::max),
    )
}

fn atomic_ad_blocks_for_group(group: &StatsAdGroup) -> Vec<(f64, f64)> {
    let mut segments = group.segments.clone();
    segments.sort_by(|a, b| {
        a.start_time
            .partial_cmp(&b.start_time)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    if segments.is_empty() {
        return Vec::new();
    }
    let mut blocks = Vec::new();
    let mut current_start = segments[0].start_time;
    let mut current_end = segments[0].end_time;
    for segment in segments.iter().skip(1) {
        if segment.start_time - current_end <= 10.0 {
            current_end = current_end.max(segment.end_time);
        } else {
            blocks.push((current_start, current_end));
            current_start = segment.start_time;
            current_end = segment.end_time;
        }
    }
    blocks.push((current_start, current_end));
    blocks
}

fn project_atomic_block(block: (f64, f64), refined: &[RefinedBoundaryRow]) -> (f64, f64) {
    let mut best: Option<&RefinedBoundaryRow> = None;
    let mut best_overlap = 0.0;
    for boundary in refined {
        let overlap = (block.1 + 1.5).min(boundary.orig_end + 1.5)
            - (block.0 - 1.5).max(boundary.orig_start - 1.5);
        if overlap > best_overlap {
            best_overlap = overlap;
            best = Some(boundary);
        }
    }
    best.filter(|_| best_overlap > 0.0)
        .map(|boundary| (boundary.refined_start, boundary.refined_end))
        .unwrap_or(block)
}

fn parse_refined_boundaries_full(raw: Option<&str>) -> Vec<RefinedBoundaryRow> {
    let Some(raw) = raw else { return Vec::new() };
    let Ok(Value::Array(items)) = serde_json::from_str::<Value>(raw) else {
        return Vec::new();
    };
    items
        .iter()
        .filter_map(|item| {
            let object = item.as_object()?;
            let orig_start = value_to_f64(object.get("orig_start")?)?;
            let orig_end = value_to_f64(object.get("orig_end")?)?;
            let refined_start = value_to_f64(object.get("refined_start")?)?;
            let refined_end = value_to_f64(object.get("refined_end")?)?;
            (orig_end > orig_start && refined_end > refined_start).then_some(RefinedBoundaryRow {
                orig_start,
                orig_end,
                refined_start,
                refined_end,
            })
        })
        .collect()
}

fn normalize_audio_label(label: &str) -> String {
    label.trim().replace('_', "").to_lowercase()
}

fn extract_audio_windows(
    segments: &[StatsAudioSegmentRow],
    include_speech: bool,
) -> Vec<(f64, f64)> {
    let allowed: HashSet<&str> = if include_speech {
        ["music", "silence", "noenergy", "speech"]
            .into_iter()
            .collect()
    } else {
        ["music", "silence", "noenergy"].into_iter().collect()
    };
    let windows = segments
        .iter()
        .filter(|segment| allowed.contains(normalize_audio_label(&segment.label).as_str()))
        .filter(|segment| segment.end_time > segment.start_time)
        .map(|segment| (segment.start_time, segment.end_time))
        .collect();
    merge_float_windows(windows, 0.75)
}

fn bridge_ad_windows_with_audio(
    ad_windows: &[(f64, f64)],
    audio_windows: &[(f64, f64)],
) -> Vec<(f64, f64)> {
    let merged_ads = merge_float_windows(ad_windows.to_vec(), 0.0);
    if merged_ads.is_empty() || merged_ads.len() == 1 {
        return merged_ads;
    }
    let merged_audio = merge_float_windows(audio_windows.to_vec(), 0.75);
    if merged_audio.is_empty() {
        return merged_ads;
    }
    let mut bridged = vec![merged_ads[0]];
    for (next_start, next_end) in merged_ads.into_iter().skip(1) {
        let (current_start, current_end) = *bridged.last().unwrap();
        if gap_is_covered_by_audio(current_end, next_start, &merged_audio, 0.75) {
            *bridged.last_mut().unwrap() = (current_start, next_end);
        } else {
            bridged.push((next_start, next_end));
        }
    }
    bridged
}

fn expand_episode_edge_ad_windows_with_audio(
    ad_windows: &[(f64, f64)],
    edge_audio_windows: &[(f64, f64)],
) -> Vec<(f64, f64)> {
    let mut expanded = ad_windows.to_vec();
    expanded.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    if expanded.is_empty() {
        return expanded;
    }
    let merged_audio = merge_float_windows(edge_audio_windows.to_vec(), 0.75);
    if merged_audio.is_empty() {
        return expanded;
    }
    let (first_start, first_end) = expanded[0];
    if first_start <= 30.0 {
        let mut coverage_start = first_start;
        let mut changed = false;
        for (audio_start, audio_end) in merged_audio.iter().rev() {
            if *audio_end < coverage_start - 0.75 {
                break;
            }
            if *audio_start > coverage_start + 0.75 {
                continue;
            }
            coverage_start = coverage_start.min(*audio_start);
            changed = true;
        }
        if changed && coverage_start <= 30.0 {
            expanded[0] = (coverage_start.max(0.0), first_end);
        }
    }
    expanded
}

fn gap_is_covered_by_audio(
    gap_start: f64,
    gap_end: f64,
    audio_windows: &[(f64, f64)],
    tolerance: f64,
) -> bool {
    if gap_end <= gap_start {
        return true;
    }
    let mut coverage = gap_start;
    for (audio_start, audio_end) in audio_windows {
        if *audio_end < coverage - tolerance {
            continue;
        }
        if *audio_start > coverage + tolerance {
            return false;
        }
        coverage = coverage.max(*audio_end);
        if coverage >= gap_end - tolerance {
            return true;
        }
    }
    false
}

fn merge_float_windows(mut windows: Vec<(f64, f64)>, gap_seconds: f64) -> Vec<(f64, f64)> {
    windows.retain(|(start, end)| end > start);
    windows.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    let mut merged: Vec<(f64, f64)> = Vec::new();
    for (start, end) in windows {
        if let Some(last) = merged.last_mut() {
            if start <= last.1 + gap_seconds {
                last.1 = last.1.max(end);
                continue;
            }
        }
        merged.push((start, end));
    }
    merged
}

fn has_transcript_content_before_first_ad(
    transcript_segments: &[StatsTranscriptSegmentRow],
    ad_windows: &[(f64, f64)],
    ad_identifications: &[StatsIdentificationRow],
) -> bool {
    if ad_windows.is_empty() {
        return false;
    }
    let first_start = ad_windows
        .iter()
        .map(|(start, _)| *start)
        .fold(f64::INFINITY, f64::min);
    if first_start > 30.0 {
        return false;
    }
    let ad_segment_ids: HashSet<i64> = ad_identifications
        .iter()
        .map(|ident| ident.transcript_segment_id)
        .collect();
    transcript_segments
        .iter()
        .any(|segment| segment.start_time < first_start && !ad_segment_ids.contains(&segment.id))
}

fn resolve_original_duration_seconds(
    post_duration: Option<f64>,
    transcript_segments: &[StatsTranscriptSegmentRow],
    bleep_windows: &[(f64, f64)],
    ad_time_seconds: f64,
) -> f64 {
    let mut cut_duration = post_duration.unwrap_or(0.0);
    if let Some(max_bleep_end) = bleep_windows.iter().map(|(_, end)| *end).reduce(f64::max) {
        if max_bleep_end > cut_duration {
            cut_duration = max_bleep_end;
        }
    }
    let transcript_duration = transcript_segments
        .iter()
        .map(|segment| segment.end_time)
        .reduce(f64::max)
        .unwrap_or(0.0);
    if post_duration.is_some() {
        cut_duration + ad_time_seconds
    } else {
        transcript_duration.max(cut_duration)
    }
}

fn build_edited_timeline_ad_markers(ad_windows: &[(f64, f64)]) -> Vec<Value> {
    let mut sorted = ad_windows.to_vec();
    sorted.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    let mut removed_before = 0.0;
    let mut markers = Vec::new();
    for (start, end) in sorted {
        let removed = end - start;
        if removed <= 0.0 {
            continue;
        }
        let edited_time = (start - removed_before).max(0.0);
        markers.push(json!({
            "edited_start_time": round_to(edited_time, 3),
            "edited_end_time": round_to(edited_time, 3),
            "original_start_time": round_to(start, 3),
            "original_end_time": round_to(end, 3),
            "removed_duration_seconds": round_to(removed, 3),
        }));
        removed_before += removed;
    }
    markers
}

fn build_edited_timeline_bleep_windows(
    bleep_windows: &[(f64, f64)],
    removed_windows: &[(f64, f64)],
) -> Vec<Value> {
    let mut edited = Vec::new();
    let mut sorted_bleeps = bleep_windows.to_vec();
    sorted_bleeps.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    let mut sorted_removed = removed_windows.to_vec();
    sorted_removed.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    for window in sorted_bleeps {
        for (retained_start, retained_end) in subtract_removed_windows(window, &sorted_removed) {
            let edited_start = map_time_to_edited_timeline(retained_start, &sorted_removed);
            let edited_end = map_time_to_edited_timeline(retained_end, &sorted_removed);
            if edited_end > edited_start {
                edited.push(json!({
                    "edited_start_time": round_to(edited_start, 3),
                    "edited_end_time": round_to(edited_end, 3),
                    "original_start_time": round_to(retained_start, 3),
                    "original_end_time": round_to(retained_end, 3),
                }));
            }
        }
    }
    edited
}

fn map_time_to_edited_timeline(time: f64, removed_windows: &[(f64, f64)]) -> f64 {
    let mut removed_before = 0.0;
    for (start, end) in removed_windows {
        if time >= *end {
            removed_before += end - start;
        } else if time > *start {
            removed_before += time - start;
            break;
        } else {
            break;
        }
    }
    (time - removed_before).max(0.0)
}

fn subtract_removed_windows(window: (f64, f64), removed_windows: &[(f64, f64)]) -> Vec<(f64, f64)> {
    let mut remaining = vec![window];
    for (removed_start, removed_end) in removed_windows {
        let mut updated = Vec::new();
        for (segment_start, segment_end) in remaining {
            if *removed_end <= segment_start || *removed_start >= segment_end {
                updated.push((segment_start, segment_end));
            } else {
                if *removed_start > segment_start {
                    updated.push((segment_start, *removed_start));
                }
                if *removed_end < segment_end {
                    updated.push((*removed_end, segment_end));
                }
            }
        }
        remaining = updated
            .into_iter()
            .filter(|(start, end)| end > start)
            .collect();
    }
    remaining
}

fn build_stats_chapters(
    post: &StatsPostRow,
    feed: Option<&StatsFeedRow>,
    strategy: &str,
) -> Result<Value> {
    if strategy != "chapter" && strategy != "chapter_insert" {
        return Ok(Value::Null);
    }
    let Some(raw) = post.chapter_data.as_deref() else {
        if post.processed_audio_path.is_some() && feed.is_some() {
            return Err(anyhow!(
                "stats chapters require audio chapter read; falling back to Python"
            ));
        }
        return Ok(Value::Null);
    };
    let data: Value = serde_json::from_str(raw).unwrap_or(Value::Null);
    let kept = data
        .get("chapters_kept")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let removed = data
        .get("chapters_removed")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if kept.is_empty() && removed.is_empty() {
        return Ok(Value::Null);
    }
    Ok(json!({
        "chapters_kept": kept,
        "chapters_removed": removed,
        "chapters_kept_count": kept.len(),
        "chapters_removed_count": removed.len(),
        "filter_strings": feed.and_then(|feed| feed.chapter_filter_strings.clone()),
    }))
}

fn build_related_logs_for_stats(
    log_path: &Path,
    post: &StatsPostRow,
    recent_jobs: &[StatsProcessingJobRow],
) -> Value {
    let latest_job_id = recent_jobs.first().map(|job| job.id.clone());
    let Ok(lines) = tail_log_lines(log_path, 1_000_000) else {
        return json!({ "latest_job_id": latest_job_id, "entries": [] });
    };
    if lines.is_empty() {
        return json!({ "latest_job_id": latest_job_id, "entries": [] });
    }
    let recent_job_ids: HashSet<String> = recent_jobs.iter().map(|job| job.id.clone()).collect();
    let post_id_text = post.id.to_string();
    let mut entries = Vec::new();
    static LINE_RE: OnceLock<Regex> = OnceLock::new();
    let line_re = LINE_RE.get_or_init(|| {
        Regex::new(r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) (?P<level>[A-Z]+)\s+(?P<message>.*)$").unwrap()
    });
    for line in lines {
        let Some(caps) = line_re.captures(&line) else {
            continue;
        };
        let message = caps.name("message").map(|m| m.as_str()).unwrap_or("");
        let job_id = extract_log_field(message, "job_id");
        let post_guid = extract_log_field(message, "post_guid");
        let matches_job = job_id
            .as_ref()
            .map(|value| recent_job_ids.contains(value))
            .unwrap_or(false);
        let matches_guid = post_guid.as_deref() == Some(post.guid.as_str());
        let matches_post_id = message.contains(&format!("post_id={post_id_text}"))
            || message.contains(&format!("post {post_id_text}"));
        if !(matches_job || matches_guid || matches_post_id) {
            continue;
        }
        let step_name = extract_step_name(message);
        entries.push(json!({
            "timestamp": caps.name("timestamp").map(|m| m.as_str()).unwrap_or(""),
            "level": caps.name("level").map(|m| m.as_str()).unwrap_or(""),
            "stage": infer_log_stage(message, step_name.as_deref()),
            "message": message,
            "job_id": job_id,
            "step_name": step_name,
        }));
    }
    let keep_from = entries.len().saturating_sub(120);
    json!({
        "latest_job_id": latest_job_id,
        "entries": entries.into_iter().skip(keep_from).collect::<Vec<_>>(),
    })
}

fn tail_log_lines(path: &Path, max_bytes: u64) -> Result<Vec<String>> {
    if !path.exists() || !path.is_file() {
        return Ok(Vec::new());
    }
    let mut file = fs::File::open(path)?;
    let file_size = file.metadata()?.len();
    let read_size = file_size.min(max_bytes);
    use std::io::{Read, Seek, SeekFrom};
    file.seek(SeekFrom::Start(file_size.saturating_sub(read_size)))?;
    let mut payload = Vec::new();
    file.read_to_end(&mut payload)?;
    let text = String::from_utf8_lossy(&payload);
    let mut lines: Vec<String> = text.lines().map(ToString::to_string).collect();
    if read_size < file_size && !lines.is_empty() {
        lines.remove(0);
    }
    Ok(lines)
}

fn log_field_regex(field_name: &str) -> &'static Regex {
    static CACHE: OnceLock<Mutex<HashMap<String, &'static Regex>>> = OnceLock::new();
    let cache = CACHE.get_or_init(|| Mutex::new(HashMap::new()));
    let mut guard = cache.lock().unwrap();
    if let Some(re) = guard.get(field_name) {
        return re;
    }
    let pattern = format!(r"\b{}=([^\s]+)", regex::escape(field_name));
    let leaked: &'static Regex = Box::leak(Box::new(Regex::new(&pattern).unwrap()));
    guard.insert(field_name.to_string(), leaked);
    leaked
}

fn extract_log_field(message: &str, field_name: &str) -> Option<String> {
    log_field_regex(field_name)
        .captures(message)
        .and_then(|caps| caps.get(1).map(|m| m.as_str().to_string()))
}

fn extract_step_name(message: &str) -> Option<String> {
    static STEP_NAME_RE: OnceLock<Regex> = OnceLock::new();
    let re = STEP_NAME_RE.get_or_init(|| Regex::new(r"\bstep_name=(.*?)(?:\s+\w+=|$)").unwrap());
    re.captures(message)
        .and_then(|caps| caps.get(1).map(|m| m.as_str().trim().to_string()))
        .filter(|value| !value.is_empty())
}

fn infer_log_stage(message: &str, step_name: Option<&str>) -> &'static str {
    let searchable = format!("{} {}", step_name.unwrap_or(""), message).to_lowercase();
    if searchable.contains("download") {
        "download"
    } else if searchable.contains("transcrib") || searchable.contains("whisper") {
        "transcription"
    } else if searchable.contains("chapter") {
        "chapters"
    } else if searchable.contains("identifying ads")
        || searchable.contains("classif")
        || searchable.contains("identification")
        || searchable.contains("boundary")
        || searchable.contains("modelcall")
        || searchable.contains("model call")
        || searchable.contains("llm")
    {
        "classification"
    } else if searchable.contains("processing audio")
        || searchable.contains("audio processor")
        || searchable.contains("ffmpeg")
        || searchable.contains("removed segment")
        || searchable.contains("processed audio")
    {
        "audio"
    } else if searchable.contains("[job_status")
        || searchable.contains("starting processing")
        || searchable.contains("processing complete")
        || searchable.contains("cancel")
        || searchable.contains("unexpected error")
        || searchable.contains("failed")
    {
        "job"
    } else {
        "general"
    }
}

fn build_file_debug(path_value: Option<&str>) -> Value {
    let Some(path_value) = path_value else {
        return json!({
            "path": Value::Null,
            "absolute_path": Value::Null,
            "exists": false,
            "is_file": false,
            "size_bytes": Value::Null,
        });
    };
    let path = Path::new(path_value);
    match fs::metadata(path) {
        Ok(metadata) => json!({
            "path": path_value,
            "absolute_path": path.canonicalize().ok().map(|path| path.to_string_lossy().to_string()),
            "exists": true,
            "is_file": metadata.is_file(),
            "size_bytes": if metadata.is_file() { Some(metadata.len()) } else { None },
        }),
        Err(error) => json!({
            "path": path_value,
            "absolute_path": path.canonicalize().ok().map(|path| path.to_string_lossy().to_string()),
            "exists": false,
            "is_file": false,
            "size_bytes": Value::Null,
            "error": error.to_string(),
        }),
    }
}

fn probe_audio_path(input: &Path) -> Result<ProbeResponse> {
    let output = Command::new("ffprobe")
        .arg("-v")
        .arg("error")
        .arg("-show_entries")
        .arg("format=duration")
        .arg("-of")
        .arg("json")
        .arg(input)
        .output()
        .with_context(|| "failed to run ffprobe")?;

    if !output.status.success() {
        return Err(anyhow!(
            "ffprobe failed with status {}: {}",
            output.status,
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }

    let payload: Value =
        serde_json::from_slice(&output.stdout).context("failed to parse ffprobe JSON")?;
    let duration_seconds = payload
        .get("format")
        .and_then(|format| format.get("duration"))
        .and_then(Value::as_str)
        .ok_or_else(|| anyhow!("ffprobe response did not include format.duration"))?
        .parse::<f64>()
        .context("ffprobe duration was not a number")?;

    if !duration_seconds.is_finite() || duration_seconds < 0.0 {
        return Err(anyhow!("ffprobe duration was invalid"));
    }

    Ok(ProbeResponse {
        duration_ms: (duration_seconds * 1000.0).round() as u64,
    })
}

fn cut_audio(args: AudioCutArgs) -> Result<OkResponse> {
    let duration_ms = probe_audio_path(&args.input)?.duration_ms;
    let windows = read_windows_ms(&args.windows_json)?;
    let encoding = EncodingOptions::new(
        args.encoding.clone(),
        args.cbr_bitrate_bps,
        args.vbr_quality,
    );

    match args.mode {
        CutMode::Exact => {
            cut_audio_simple(&args.input, &args.output, &windows, duration_ms, &encoding)?
        }
        CutMode::Fade => cut_audio_with_fade(
            &args.input,
            &args.output,
            &windows,
            duration_ms,
            args.fade_ms,
            &encoding,
        )?,
    }

    Ok(OkResponse { ok: true })
}

const BLEEP_MAX_WINDOWS_PER_PASS: usize = 96;

fn bleep_audio(args: AudioBleepArgs) -> Result<OkResponse> {
    let duration_ms = probe_audio_path(&args.input)?.duration_ms;
    let windows = read_windows_ms(&args.windows_json)?;
    if windows.is_empty() {
        fs::copy(&args.input, &args.output).with_context(|| "failed to copy input audio")?;
        return Ok(OkResponse { ok: true });
    }
    let encoding = EncodingOptions::new(
        args.encoding.clone(),
        args.cbr_bitrate_bps,
        args.vbr_quality,
    );

    let chunks: Vec<&[(u64, u64)]> = windows.chunks(BLEEP_MAX_WINDOWS_PER_PASS).collect();
    let total_passes = chunks.len();

    if total_passes == 1 {
        apply_bleep_pass_mp3(
            &args.input,
            &args.output,
            chunks[0],
            duration_ms,
            args.beep_frequency_hz,
            args.beep_volume,
            args.duck_volume,
            args.fade_ms,
            &encoding,
        )?;
        return Ok(OkResponse { ok: true });
    }

    // Multi-pass: keep intermediates lossless (WAV) so only the final mp3 encode is lossy.
    let temp_dir = tempfile::tempdir().with_context(|| "failed to create temp directory")?;
    let mut current_input = args.input.clone();
    for (idx, chunk) in chunks.iter().enumerate() {
        let is_last = idx == total_passes - 1;
        if is_last {
            apply_bleep_pass_mp3(
                &current_input,
                &args.output,
                chunk,
                duration_ms,
                args.beep_frequency_hz,
                args.beep_volume,
                args.duck_volume,
                args.fade_ms,
                &encoding,
            )?;
        } else {
            let pass_output = temp_dir.path().join(format!("bleep_pass_{idx}.wav"));
            apply_bleep_pass_wav(
                &current_input,
                &pass_output,
                chunk,
                duration_ms,
                args.beep_frequency_hz,
                args.beep_volume,
                args.duck_volume,
                args.fade_ms,
            )?;
            current_input = pass_output;
        }
    }
    Ok(OkResponse { ok: true })
}

// Build the bleep filter graph using:
//   * Voice: a chain of per-window `volume` filters with `enable=` so each
//     filter only fires inside its own zone. Each filter ramps the gain
//     between 1.0 and `duck` over `fade_ms` so window edges crossfade
//     instead of cutting abruptly (which produced audible clicks).
//   * Beep: one `sine` source per window, faded in/out and delayed to the
//     window start, then `amix` of all beep sources with the ducked voice.
// Both sides have matching crossfade curves so the voice attenuating and the
// beep coming in happen smoothly across the fade window.
fn bleep_filter_complex(
    windows: &[(u64, u64)],
    duration_ms: u64,
    beep_frequency_hz: u32,
    beep_volume: f32,
    duck_volume: f32,
    fade_ms: u32,
) -> String {
    let fade_s = (f64::from(fade_ms.max(1))) / 1000.0;
    let duration_s = duration_ms as f64 / 1000.0;

    // Expand each window by fade_ms on each side, then merge so adjacent
    // fade zones don't overlap and double-attenuate the voice.
    let zones: Vec<(f64, f64)> = {
        let fade_ms_u64 = u64::from(fade_ms);
        let expanded: Vec<(u64, u64)> = windows
            .iter()
            .map(|&(s, e)| (s.saturating_sub(fade_ms_u64), e.saturating_add(fade_ms_u64)))
            .collect();
        merge_windows(expanded)
            .into_iter()
            .map(|(zs, ze)| {
                (
                    (zs as f64 / 1000.0).max(0.0),
                    (ze as f64 / 1000.0).min(duration_s),
                )
            })
            .filter(|(zs, ze)| ze > zs)
            .collect()
    };

    let voice_coef = (1.0 - f64::from(duck_volume)).clamp(0.0, 1.0);

    let voice_filters: Vec<String> = zones
        .iter()
        .map(|&(zs, ze)| {
            // trapezoidal bump: 0 outside the zone, ramps 0→1 over fade_s at the
            // leading edge, holds at 1, ramps 1→0 at the trailing edge.
            format!(
                "volume='1-{coef:.4}*max(0,min(1,min((t-{zs:.4})/{r:.5},({ze:.4}-t)/{r:.5})))':eval=frame:enable='between(t,{zs:.4},{ze:.4})'",
                coef = voice_coef,
                zs = zs,
                ze = ze,
                r = fade_s,
            )
        })
        .collect();

    let voice_chain = if voice_filters.is_empty() {
        "[0:a]anull[ducked]".to_string()
    } else {
        format!("[0:a]{}[ducked]", voice_filters.join(","))
    };

    let mut beep_parts: Vec<String> = Vec::new();
    let mut beep_labels: Vec<String> = Vec::new();
    for (i, &(zs, ze)) in zones.iter().enumerate() {
        let beep_dur = ze - zs;
        if beep_dur <= 0.0 {
            continue;
        }
        let fade_actual = fade_s.min(beep_dur / 2.0);
        let fade_out_start = (beep_dur - fade_actual).max(0.0);
        let delay_ms_int = (zs * 1000.0).round() as u64;
        let label = format!("b{i}");
        beep_parts.push(format!(
            "sine=frequency={freq}:duration={dur:.4}:sample_rate=44100,\
             afade=t=in:d={fr:.5},\
             afade=t=out:st={fo:.5}:d={fr:.5},\
             volume={vol:.4},\
             adelay={delay}[{label}]",
            freq = beep_frequency_hz,
            dur = beep_dur,
            fr = fade_actual,
            fo = fade_out_start,
            vol = beep_volume,
            delay = delay_ms_int,
            label = label,
        ));
        beep_labels.push(format!("[{label}]"));
    }

    let mix = if beep_labels.is_empty() {
        "[ducked]anull[out]".to_string()
    } else {
        format!(
            "[ducked]{labels}amix=inputs={n}:duration=first:dropout_transition=0:normalize=0[out]",
            labels = beep_labels.join(""),
            n = beep_labels.len() + 1,
        )
    };

    let mut parts = vec![voice_chain];
    parts.extend(beep_parts);
    parts.push(mix);
    parts.join(";")
}

#[allow(clippy::too_many_arguments)]
fn apply_bleep_pass_mp3(
    input: &Path,
    output: &Path,
    windows: &[(u64, u64)],
    duration_ms: u64,
    beep_frequency_hz: u32,
    beep_volume: f32,
    duck_volume: f32,
    fade_ms: u32,
    encoding: &EncodingOptions,
) -> Result<()> {
    let filter = bleep_filter_complex(
        windows,
        duration_ms,
        beep_frequency_hz,
        beep_volume,
        duck_volume,
        fade_ms,
    );
    run_filtered_output(input, output, &filter, encoding)
}

#[allow(clippy::too_many_arguments)]
fn apply_bleep_pass_wav(
    input: &Path,
    output: &Path,
    windows: &[(u64, u64)],
    duration_ms: u64,
    beep_frequency_hz: u32,
    beep_volume: f32,
    duck_volume: f32,
    fade_ms: u32,
) -> Result<()> {
    let filter = bleep_filter_complex(
        windows,
        duration_ms,
        beep_frequency_hz,
        beep_volume,
        duck_volume,
        fade_ms,
    );
    let mut command = Command::new("ffmpeg");
    command
        .arg("-y")
        .arg("-v")
        .arg("error")
        .arg("-i")
        .arg(input)
        .arg("-filter_complex")
        .arg(&filter)
        .arg("-map")
        .arg("[out]")
        .arg("-codec:a")
        .arg("pcm_s16le")
        .arg(output);
    run_command(command, "ffmpeg filter (wav intermediate)")
}

fn split_audio(args: AudioSplitArgs) -> Result<SplitResponse> {
    if args.chunk_size_bytes == 0 {
        return Err(anyhow!("chunk_size_bytes must be a positive integer"));
    }

    fs::create_dir_all(&args.out_dir).with_context(|| "failed to create output directory")?;
    let duration_ms = probe_audio_path(&args.input)?.duration_ms;
    let file_size_bytes = fs::metadata(&args.input)
        .with_context(|| "failed to read input metadata")?
        .len();
    if file_size_bytes == 0 {
        return Err(anyhow!("cannot split zero-byte audio file"));
    }

    let chunk_ratio = args.chunk_size_bytes as f64 / file_size_bytes as f64;
    let chunk_duration_ms = ((duration_ms as f64 * chunk_ratio).ceil() as u64).max(1);
    let num_chunks = ((duration_ms as f64 / chunk_duration_ms as f64).ceil() as u64).max(1);

    let mut chunks = Vec::new();
    for index in 0..num_chunks {
        let start_offset_ms = index * chunk_duration_ms;
        if start_offset_ms >= duration_ms {
            break;
        }
        let end_offset_ms = duration_ms.min((index + 1) * chunk_duration_ms);
        let output_path = args.out_dir.join(format!("{index}.mp3"));
        trim_file(&args.input, &output_path, start_offset_ms, end_offset_ms)?;
        chunks.push(SplitChunk {
            path: output_path.to_string_lossy().into_owned(),
            offset_ms: start_offset_ms,
        });
    }

    Ok(SplitResponse { chunks })
}

fn cut_audio_with_fade(
    input: &Path,
    output: &Path,
    windows: &[(u64, u64)],
    duration_ms: u64,
    fade_ms: u32,
    encoding: &EncodingOptions,
) -> Result<()> {
    let fade_ms = fade_ms as u64;
    let mut streams = Vec::new();
    let mut last_end = 0;
    for (start_ms, end_ms) in windows {
        if *start_ms > last_end {
            streams.push((last_end, *start_ms, None));
        }
        streams.push((*start_ms, (*start_ms + fade_ms).min(*end_ms), Some("out")));
        streams.push((end_ms.saturating_sub(fade_ms), *end_ms, Some("in")));
        last_end = *end_ms;
    }
    if last_end < duration_ms {
        streams.push((last_end, duration_ms, None));
    }

    let mut filter_parts = Vec::new();
    let mut labels = Vec::new();
    for (index, (start_ms, end_ms, fade)) in streams.iter().enumerate() {
        if end_ms <= start_ms {
            continue;
        }
        let label = format!("a{index}");
        let mut part = format!(
            "[0:a]atrim=start={:.3}:end={:.3},asetpts=PTS-STARTPTS",
            *start_ms as f64 / 1000.0,
            *end_ms as f64 / 1000.0
        );
        if let Some(direction) = fade {
            part.push_str(&format!(
                ",afade=t={direction}:ss=0:d={:.3}",
                fade_ms as f64 / 1000.0
            ));
        }
        part.push_str(&format!("[{label}]"));
        filter_parts.push(part);
        labels.push(format!("[{label}]"));
    }

    if labels.is_empty() {
        return Err(anyhow!("no audio segments to keep after removal"));
    }

    filter_parts.push(format!(
        "{}concat=n={}:v=0:a=1[out]",
        labels.join(""),
        labels.len()
    ));
    run_filtered_output(input, output, &filter_parts.join(";"), encoding)
}

fn cut_audio_simple(
    input: &Path,
    output: &Path,
    windows: &[(u64, u64)],
    duration_ms: u64,
    encoding: &EncodingOptions,
) -> Result<()> {
    let keep_segments = keep_segments(windows, duration_ms);
    if keep_segments.is_empty() {
        return Err(anyhow!("no audio segments to keep after removal"));
    }

    let temp_dir = tempfile::tempdir().with_context(|| "failed to create temp directory")?;
    let mut segment_files = Vec::new();
    for (index, (start_ms, end_ms)) in keep_segments.iter().enumerate() {
        let segment_path = temp_dir.path().join(format!("segment_{index}.wav"));
        trim_file_lossless(input, &segment_path, *start_ms, *end_ms)?;
        segment_files.push(segment_path);
    }

    let concat_list_path = temp_dir.path().join("concat_list.txt");
    let mut concat_list =
        fs::File::create(&concat_list_path).with_context(|| "failed to create concat list")?;
    for segment_file in segment_files {
        writeln!(concat_list, "file '{}'", segment_file.display())
            .with_context(|| "failed to write concat list")?;
    }

    let mut command = Command::new("ffmpeg");
    command
        .arg("-y")
        .arg("-v")
        .arg("error")
        .arg("-f")
        .arg("concat")
        .arg("-safe")
        .arg("0")
        .arg("-i")
        .arg(concat_list_path)
        .arg("-codec:a")
        .arg("libmp3lame");
    add_encoding_args(&mut command, encoding);
    command.arg(output);
    run_command(command, "ffmpeg concat")
}

fn trim_file(input: &Path, output: &Path, start_ms: u64, end_ms: u64) -> Result<()> {
    let duration_ms = end_ms.saturating_sub(start_ms);
    if duration_ms == 0 {
        return Ok(());
    }

    let mut command = Command::new("ffmpeg");
    command
        .arg("-y")
        .arg("-v")
        .arg("error")
        .arg("-ss")
        .arg(format!("{:.3}", start_ms as f64 / 1000.0))
        .arg("-t")
        .arg(format!("{:.3}", duration_ms as f64 / 1000.0))
        .arg("-i")
        .arg(input)
        .arg("-codec:a")
        .arg("copy")
        .arg("-vn")
        .arg(output);
    run_command(command, "ffmpeg trim")
}

fn trim_file_lossless(input: &Path, output: &Path, start_ms: u64, end_ms: u64) -> Result<()> {
    let duration_ms = end_ms.saturating_sub(start_ms);
    let mut command = Command::new("ffmpeg");
    command
        .arg("-y")
        .arg("-v")
        .arg("error")
        .arg("-ss")
        .arg(format!("{:.3}", start_ms as f64 / 1000.0))
        .arg("-t")
        .arg(format!("{:.3}", duration_ms as f64 / 1000.0))
        .arg("-i")
        .arg(input)
        .arg("-codec:a")
        .arg("pcm_s16le")
        .arg("-vn");
    command.arg(output);
    run_command(command, "ffmpeg segment")
}

fn run_filtered_output(
    input: &Path,
    output: &Path,
    filter: &str,
    encoding: &EncodingOptions,
) -> Result<()> {
    let mut command = Command::new("ffmpeg");
    command
        .arg("-y")
        .arg("-v")
        .arg("error")
        .arg("-i")
        .arg(input)
        .arg("-filter_complex")
        .arg(filter)
        .arg("-map")
        .arg("[out]")
        .arg("-codec:a")
        .arg("libmp3lame");
    add_encoding_args(&mut command, encoding);
    command.arg(output);
    run_command(command, "ffmpeg filter")
}

fn run_command(mut command: Command, label: &str) -> Result<()> {
    let output = command
        .output()
        .with_context(|| format!("failed to run {label}"))?;
    if !output.status.success() {
        return Err(anyhow!(
            "{label} failed with status {}: {}",
            output.status,
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(())
}

fn add_encoding_args(command: &mut Command, encoding: &EncodingOptions) {
    match &encoding.mode {
        Encoding::Vbr => {
            command
                .arg("-q:a")
                .arg(encoding.vbr_quality.unwrap_or(2).to_string());
        }
        Encoding::Cbr => {
            command
                .arg("-b:a")
                .arg(encoding.cbr_bitrate_bps.unwrap_or(192_000).to_string());
        }
    }
}

fn read_windows_ms(path: &Path) -> Result<Vec<(u64, u64)>> {
    let data = fs::read_to_string(path).with_context(|| "failed to read windows JSON")?;
    let windows: Vec<WindowMs> =
        serde_json::from_str(&data).with_context(|| "failed to parse windows JSON")?;
    Ok(merge_windows(
        windows
            .into_iter()
            .filter_map(|WindowMs(start, end)| (end > start).then_some((start, end)))
            .collect(),
    ))
}

fn merge_windows(mut windows: Vec<(u64, u64)>) -> Vec<(u64, u64)> {
    windows.sort_by_key(|window| window.0);
    let mut merged: Vec<(u64, u64)> = Vec::new();
    for (start, end) in windows {
        match merged.last_mut() {
            Some((_, prev_end)) if start <= *prev_end => {
                *prev_end = (*prev_end).max(end);
            }
            _ => merged.push((start, end)),
        }
    }
    merged
}

fn keep_segments(windows: &[(u64, u64)], duration_ms: u64) -> Vec<(u64, u64)> {
    let mut keep = Vec::new();
    let mut last_end = 0;
    for (start, end) in windows {
        if *start > last_end {
            keep.push((last_end, *start));
        }
        last_end = *end;
    }
    if last_end < duration_ms {
        keep.push((last_end, duration_ms));
    }
    keep
}

fn normalize_word_timestamps(args: TranscriptNormalizeArgs) -> Result<OkResponse> {
    let data = fs::read_to_string(&args.input)
        .with_context(|| "failed to read transcript word timestamp artifact")?;
    let payload: Value =
        serde_json::from_str(&data).with_context(|| "failed to parse transcript JSON")?;
    let Value::Array(raw_segments) = payload else {
        fs::write(&args.output, b"null")
            .with_context(|| "failed to write normalized transcript JSON")?;
        return Ok(OkResponse { ok: true });
    };

    let mut normalized_segments = Vec::new();
    for raw_segment in raw_segments {
        let Value::Object(segment_map) = raw_segment else {
            continue;
        };
        let Some(sequence_num) = segment_map.get("sequence_num").and_then(value_to_i64) else {
            continue;
        };
        let Some(Value::Array(words)) = segment_map.get("words") else {
            continue;
        };

        let mut normalized_words = Vec::new();
        for word_payload in words {
            let Value::Object(word_map) = word_payload else {
                continue;
            };
            let Some(raw_word) = word_map.get("word") else {
                continue;
            };
            let Some(word) = value_to_string(raw_word) else {
                continue;
            };
            let Some(start) = word_map.get("start").and_then(value_to_f64) else {
                continue;
            };
            let Some(end) = word_map.get("end").and_then(value_to_f64) else {
                continue;
            };
            if end < start {
                continue;
            }
            let score = word_map.get("score").and_then(value_to_f64);
            normalized_words.push(NormalizedWord {
                word,
                start,
                end,
                score,
            });
        }

        if !normalized_words.is_empty() {
            normalized_segments.push(NormalizedWordSegment {
                sequence_num,
                words: normalized_words,
            });
        }
    }

    let normalized_payload = if normalized_segments.is_empty() {
        Value::Null
    } else {
        serde_json::to_value(normalized_segments)?
    };
    fs::write(&args.output, serde_json::to_vec(&normalized_payload)?)
        .with_context(|| "failed to write normalized transcript JSON")?;
    Ok(OkResponse { ok: true })
}

fn export_word_timestamps(args: TranscriptExportArgs) -> Result<TranscriptExportResponse> {
    let conn = Connection::open_with_flags(
        &args.db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_URI,
    )
    .with_context(|| "failed to open sqlite database read-only")?;
    conn.busy_timeout(std::time::Duration::from_secs(30))
        .with_context(|| "failed to set sqlite busy timeout")?;
    conn.pragma_update(None, "query_only", true)
        .with_context(|| "failed to enable sqlite query_only mode")?;

    let raw_json: Option<String> = conn
        .query_row(
            "SELECT transcript_word_timestamps FROM post WHERE id = ?1",
            [args.post_id],
            |row| row.get(0),
        )
        .with_context(|| "failed to query transcript_word_timestamps")?;

    let transcript_word_timestamps = match raw_json {
        Some(raw_json) => serde_json::from_str(&raw_json)
            .with_context(|| "stored transcript_word_timestamps was not valid JSON")?,
        None => Value::Null,
    };

    Ok(TranscriptExportResponse {
        transcript_word_timestamps,
    })
}

fn render_feed(args: FeedRenderArgs) -> Result<XmlResponse> {
    let conn = open_readonly_sqlite(&args.db)?;
    let feed = conn
        .query_row(
            "SELECT id, title, description, image_url, last_changed_at FROM feed WHERE id = ?1",
            [args.feed_id],
            |row| {
                Ok(FeedRow {
                    id: row.get(0)?,
                    title: row.get(1)?,
                    description: row.get(2)?,
                    image_url: row.get(3)?,
                    last_changed_at: row.get(4)?,
                })
            },
        )
        .with_context(|| "failed to query feed")?;

    let posts = if args.include_unprocessed {
        query_posts(
            &conn,
            "SELECT NULL, title, guid, processed_audio_path, description, release_date, duration, image_url, chapter_data \
             FROM post WHERE feed_id = ?1 ORDER BY release_date DESC, id DESC",
            [feed.id],
        )?
    } else {
        query_posts(
            &conn,
            "SELECT NULL, title, guid, processed_audio_path, description, release_date, duration, image_url, chapter_data \
             FROM post WHERE feed_id = ?1 AND whitelisted = 1 AND processed_audio_path IS NOT NULL \
             ORDER BY release_date DESC, id DESC",
            [feed.id],
        )?
    };

    let link = append_feed_token(
        &format!("{}/feed/{}", args.base_url.trim_end_matches('/'), feed.id),
        args.feed_token.as_deref(),
        args.feed_secret.as_deref(),
    );
    let feed_title = format!("[podly] {}", feed.title);
    let last_build_date = format_rfc2822(feed.last_changed_at.as_deref());
    let xml = build_rss_xml(RssBuildArgs {
        title: &feed_title,
        link: &link,
        description: feed.description.as_deref().unwrap_or(""),
        image_url: feed.image_url.as_deref(),
        image_title: &feed.title,
        last_build_date: &last_build_date,
        base_url: &args.base_url,
        feed_token: args.feed_token.as_deref(),
        feed_secret: args.feed_secret.as_deref(),
        posts: &posts,
        prepend_feed_title: false,
    });
    Ok(XmlResponse { xml })
}

fn write_chapters(args: ChaptersWriteArgs) -> Result<OkResponse> {
    let data =
        fs::read_to_string(&args.chapters_json).with_context(|| "failed to read chapters JSON")?;
    let mut chapters: Vec<ChapterPayload> =
        serde_json::from_str(&data).with_context(|| "failed to parse chapters JSON")?;
    if chapters.is_empty() {
        return Ok(OkResponse { ok: true });
    }
    chapters.sort_by_key(|chapter| chapter.start_time_ms);

    // Clamp chapter end_times to the real audio duration. Some readers
    // (notably Pocket Casts) silently drop chapters whose end_time exceeds
    // the file length, which can happen after ad-removal recalculation if
    // the cut math and ffmpeg's reported duration disagree by even a few ms.
    let audio_duration_ms_u64 = probe_audio_path(&args.audio).ok().map(|p| p.duration_ms);
    if let Some(duration_ms) = audio_duration_ms_u64 {
        let duration_u32 = duration_ms.min(u64::from(u32::MAX)) as u32;
        chapters.retain(|chapter| chapter.start_time_ms < duration_u32);
        for chapter in chapters.iter_mut() {
            if chapter.end_time_ms > duration_u32 {
                chapter.end_time_ms = duration_u32;
            }
        }
    }
    if chapters.is_empty() {
        return Ok(OkResponse { ok: true });
    }

    let mut tag = Tag::read_from_path(&args.audio).unwrap_or_else(|_| Tag::new());
    tag.remove("CHAP");
    tag.remove("CTOC");

    let total_duration_ms = audio_duration_ms_u64
        .map(|ms| ms.min(u64::from(u32::MAX)) as u32)
        .unwrap_or_else(|| {
            chapters
                .iter()
                .map(|chapter| chapter.end_time_ms)
                .max()
                .unwrap_or(0)
        });

    let mut chapter_ids = Vec::new();
    for (index, chapter) in chapters.into_iter().enumerate() {
        let element_id = format!("chp{index}");
        chapter_ids.push(element_id.clone());
        let title_frame = Frame::with_content("TIT2", Content::Text(chapter.title))
            .set_encoding(Some(Id3Encoding::UTF16));
        tag.add_frame(Id3Chapter {
            element_id,
            start_time: chapter.start_time_ms,
            end_time: chapter.end_time_ms,
            start_offset: 0xFFFF_FFFF,
            end_offset: 0xFFFF_FFFF,
            frames: vec![title_frame],
        });
    }

    tag.add_frame(TableOfContents {
        element_id: "toc".to_string(),
        top_level: true,
        ordered: true,
        elements: chapter_ids,
        frames: vec![],
    });

    // TLEN gives players the expected total duration; some readers (Pocket Casts)
    // discard chapters whose end_time exceeds the file duration when TLEN is absent.
    tag.remove("TLEN");
    if total_duration_ms > 0 {
        tag.add_frame(Frame::with_content(
            "TLEN",
            Content::Text(total_duration_ms.to_string()),
        ));
    }

    tag.write_to_path(&args.audio, Version::Id3v23)
        .with_context(|| "failed to write chapter ID3 tags")?;

    Ok(OkResponse { ok: true })
}

fn read_chapters(args: ChaptersReadArgs) -> Result<ChaptersReadResponse> {
    Ok(ChaptersReadResponse {
        chapters: read_chapters_from_audio(&args.audio)?,
    })
}

fn detect_chapter_ads(args: ChaptersDetectArgs) -> Result<ChaptersDetectResponse> {
    let chapters = read_chapters_from_audio(&args.audio)?;
    let filters = parse_filter_strings_csv(&args.filter_strings_csv);
    let (chapters_to_keep, chapters_to_remove) = filter_chapters_by_strings(chapters, &filters);
    let ad_segments = chapters_to_remove
        .iter()
        .map(|chapter| {
            (
                f64::from(chapter.start_time_ms) / 1000.0,
                f64::from(chapter.end_time_ms) / 1000.0,
            )
        })
        .collect();

    Ok(ChaptersDetectResponse {
        ad_segments,
        chapters_to_keep,
        chapters_to_remove,
    })
}

fn read_chapters_from_audio(audio: &Path) -> Result<Vec<ChapterResponseItem>> {
    let Ok(tag) = Tag::read_from_path(audio) else {
        return Ok(Vec::new());
    };

    let mut chapters: Vec<ChapterResponseItem> = tag
        .chapters()
        .map(|chapter| {
            let title = chapter
                .frames
                .iter()
                .find(|frame| frame.id() == "TIT2")
                .and_then(|frame| match frame.content() {
                    Content::Text(text) => Some(text.clone()),
                    _ => None,
                })
                .filter(|title| !title.is_empty())
                .unwrap_or_else(|| chapter.element_id.clone());

            ChapterResponseItem {
                element_id: chapter.element_id.clone(),
                title,
                start_time_ms: chapter.start_time,
                end_time_ms: chapter.end_time,
            }
        })
        .collect();
    chapters.sort_by_key(|chapter| chapter.start_time_ms);
    Ok(chapters)
}

fn parse_filter_strings_csv(filter_strings_csv: &str) -> Vec<String> {
    filter_strings_csv
        .split(',')
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_lowercase)
        .collect()
}

fn filter_chapters_by_strings(
    chapters: Vec<ChapterResponseItem>,
    filters: &[String],
) -> (Vec<ChapterResponseItem>, Vec<ChapterResponseItem>) {
    if filters.is_empty() {
        return (chapters, Vec::new());
    }

    chapters.into_iter().partition(|chapter| {
        let title = chapter.title.to_lowercase();
        !filters.iter().any(|filter| title.contains(filter))
    })
}

fn render_aggregate_feed(args: FeedRenderAggregateArgs) -> Result<XmlResponse> {
    let conn = open_readonly_sqlite(&args.db)?;
    let feed_ids: Vec<i64> = if args.require_auth {
        let mut stmt = conn.prepare("SELECT feed_id FROM user_feed WHERE user_id = ?1")?;
        let rows = stmt.query_map([args.user_id], |row| row.get(0))?;
        rows.collect::<std::result::Result<Vec<i64>, _>>()?
    } else {
        let mut stmt = conn.prepare("SELECT id FROM feed")?;
        let rows = stmt.query_map([], |row| row.get(0))?;
        rows.collect::<std::result::Result<Vec<i64>, _>>()?
    };

    let mut posts = Vec::new();
    for feed_id in feed_ids {
        let mut feed_posts = query_posts_with_limit(
            &conn,
            "SELECT feed.title, post.title, post.guid, post.processed_audio_path, post.description, post.release_date, post.duration, post.image_url, post.chapter_data \
             FROM post JOIN feed ON feed.id = post.feed_id \
             WHERE post.feed_id = ?1 AND post.whitelisted = 1 AND post.processed_audio_path IS NOT NULL \
             ORDER BY post.release_date DESC, post.id DESC LIMIT ?2",
            feed_id,
            args.limit_per_feed as i64,
        )?;
        posts.append(&mut feed_posts);
    }
    posts.sort_by(|a, b| b.release_date.cmp(&a.release_date));

    let last_changed_at: Option<String> = if args.require_auth {
        conn.query_row(
            "SELECT max(feed.last_changed_at) FROM feed JOIN user_feed ON user_feed.feed_id = feed.id WHERE user_feed.user_id = ?1",
            [args.user_id],
            |row| row.get(0),
        )?
    } else {
        conn.query_row("SELECT max(last_changed_at) FROM feed", [], |row| {
            row.get(0)
        })?
    };

    let link = append_feed_token(
        &format!(
            "{}/feed/user/{}",
            args.base_url.trim_end_matches('/'),
            args.user_id
        ),
        args.feed_token.as_deref(),
        args.feed_secret.as_deref(),
    );
    let title = "Podly Podcasts";
    let image_url = format!(
        "{}/static/images/logos/manifest-icon-512.maskable.png",
        args.base_url.trim_end_matches('/')
    );
    let last_build_date = format_rfc2822(last_changed_at.as_deref());
    let xml = build_rss_xml(RssBuildArgs {
        title,
        link: &link,
        description: "Aggregate feed - Last 3 processed episodes from each subscribed feed.",
        image_url: Some(&image_url),
        image_title: title,
        last_build_date: &last_build_date,
        base_url: &args.base_url,
        feed_token: args.feed_token.as_deref(),
        feed_secret: args.feed_secret.as_deref(),
        posts: &posts,
        prepend_feed_title: true,
    });
    Ok(XmlResponse { xml })
}

#[derive(Serialize)]
struct FeedRefreshPlanResponse {
    updates: Value,
    new_posts: Vec<Value>,
    existing_post_updates: Vec<Value>,
}

fn plan_feed_refresh(args: FeedRefreshPlanArgs) -> Result<FeedRefreshPlanResponse> {
    let conn = open_readonly_sqlite(&args.db)?;
    let feed = query_refresh_feed(&conn, args.feed_id)?;
    let xml = fs::read_to_string(&args.feed_xml)
        .with_context(|| format!("failed to read feed XML {}", args.feed_xml.display()))?;
    let channel_image_url = parse_channel_image_url(&xml);
    let entries = parse_feed_entries(&xml, feed.image_url.as_deref())?;

    let mut updates = serde_json::Map::new();
    if let Some(new_image_url) = channel_image_url {
        if feed.image_url.as_deref() != Some(new_image_url.as_str()) {
            updates.insert("image_url".to_string(), json!(new_image_url));
        }
    }

    let posts = query_refresh_posts(&conn, feed.id)?;
    let oldest_release_date = posts
        .iter()
        .filter_map(|post| post.release_date.as_deref())
        .min()
        .map(str::to_string);
    let posts_by_guid: HashMap<&str, &FeedRefreshPostRow> = posts
        .iter()
        .map(|post| (post.guid.as_str(), post))
        .collect();
    let posts_by_url: HashMap<&str, &FeedRefreshPostRow> = posts
        .iter()
        .map(|post| (post.download_url.as_str(), post))
        .collect();

    let mut new_posts = Vec::new();
    let mut existing_post_updates = Vec::new();
    for entry in entries {
        let mut existing = posts_by_guid.get(entry.guid.as_str()).copied();
        let mut repaired_guid: Option<&str> = None;
        if existing.is_none() {
            existing = posts_by_url.get(entry.download_url.as_str()).copied();
            if let Some(post) = existing {
                if post.guid != entry.guid {
                    repaired_guid = Some(entry.guid.as_str());
                }
            }
        }

        if let Some(post) = existing {
            let update = existing_post_refresh_update(post, &entry, repaired_guid);
            if let Some(update) = update {
                existing_post_updates.push(update);
            }
        } else {
            let is_archive = match (
                oldest_release_date.as_deref(),
                entry.release_date.as_deref(),
            ) {
                (Some(oldest), Some(release)) => {
                    release_date_prefix(release) < release_date_prefix(oldest)
                }
                _ => false,
            };
            let whitelisted = args.auto_whitelist_new_posts && !is_archive;
            new_posts.push(json!({
                "guid": entry.guid,
                "title": entry.title,
                "description": entry.description,
                "download_url": entry.download_url,
                "release_date": entry.release_date,
                "duration": entry.duration,
                "image_url": entry.image_url,
                "whitelisted": whitelisted,
                "feed_id": feed.id,
            }));
        }
    }

    Ok(FeedRefreshPlanResponse {
        updates: Value::Object(updates),
        new_posts,
        existing_post_updates,
    })
}

fn query_refresh_feed(conn: &Connection, feed_id: i64) -> Result<FeedRefreshFeedRow> {
    conn.query_row(
        "SELECT id, image_url FROM feed WHERE id = ?1",
        [feed_id],
        |row| {
            Ok(FeedRefreshFeedRow {
                id: row.get(0)?,
                image_url: row.get(1)?,
            })
        },
    )
    .with_context(|| format!("feed {feed_id} not found"))
}

fn query_refresh_posts(conn: &Connection, feed_id: i64) -> Result<Vec<FeedRefreshPostRow>> {
    let mut stmt = conn.prepare(
        "SELECT id, guid, download_url, title, description, processed_audio_path,
                release_date, duration, image_url
           FROM post
          WHERE feed_id = ?1",
    )?;
    let rows = stmt.query_map([feed_id], |row| {
        Ok(FeedRefreshPostRow {
            id: row.get(0)?,
            guid: row.get(1)?,
            download_url: row.get(2)?,
            title: row.get(3)?,
            description: row.get(4)?,
            processed_audio_path: row.get(5)?,
            release_date: row.get(6)?,
            duration: get_duration_seconds(row, 7)?,
            image_url: row.get(8)?,
        })
    })?;
    Ok(rows.collect::<std::result::Result<Vec<_>, _>>()?)
}

fn existing_post_refresh_update(
    post: &FeedRefreshPostRow,
    entry: &ParsedFeedEntry,
    repaired_guid: Option<&str>,
) -> Option<Value> {
    let mut update = serde_json::Map::new();
    update.insert("post_id".to_string(), json!(post.id));
    if let Some(guid) = repaired_guid {
        update.insert("guid".to_string(), json!(guid));
    }
    if !entry.title.is_empty() && post.title != entry.title {
        update.insert("title".to_string(), json!(entry.title));
    }
    if post.description.as_deref().unwrap_or("") != entry.description {
        update.insert("description".to_string(), json!(entry.description));
    }
    if post.image_url != entry.image_url {
        update.insert("image_url".to_string(), json!(entry.image_url));
    }
    if post.processed_audio_path.is_none()
        && entry.duration.is_some()
        && post.duration != entry.duration
    {
        update.insert("duration".to_string(), json!(entry.duration));
    }
    if update.len() > 1 {
        Some(Value::Object(update))
    } else {
        None
    }
}

fn parse_feed_entries(xml: &str, feed_image_url: Option<&str>) -> Result<Vec<ParsedFeedEntry>> {
    let mut entries = Vec::new();
    for item in extract_xml_blocks(xml, "item") {
        let title = xml_text(&item, "title").unwrap_or_default();
        let download_url = find_feed_entry_audio_url(&item)
            .or_else(|| xml_text(&item, "guid"))
            .unwrap_or_default();
        let raw_guid = xml_text(&item, "guid").unwrap_or_default();
        let guid = if raw_guid.trim().is_empty() {
            uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_URL, download_url.as_bytes()).to_string()
        } else {
            raw_guid.trim().to_string()
        };
        entries.push(ParsedFeedEntry {
            guid,
            title: title.trim().to_string(),
            description: parse_entry_description(&item),
            download_url,
            release_date: xml_text(&item, "pubDate").and_then(|value| parse_rfc2822_to_utc(&value)),
            duration: xml_text(&item, "duration")
                .or_else(|| xml_text(&item, "itunes:duration"))
                .and_then(|value| parse_duration_seconds_string(&value)),
            image_url: parse_entry_image_url(&item).or_else(|| feed_image_url.map(str::to_string)),
        });
    }
    Ok(entries)
}

fn parse_channel_image_url(xml: &str) -> Option<String> {
    let channel = extract_xml_blocks(xml, "channel").into_iter().next()?;
    if let Some(image_block) = extract_xml_blocks(&channel, "image").into_iter().next() {
        if let Some(url) = xml_text(&image_block, "url") {
            return Some(url);
        }
    }
    parse_itunes_image_href(&channel)
}

fn parse_entry_image_url(item: &str) -> Option<String> {
    parse_itunes_image_href(item)
        .or_else(|| parse_media_thumbnail_url(item))
        .or_else(|| {
            extract_xml_blocks(item, "image")
                .into_iter()
                .next()
                .and_then(|image| {
                    xml_text(&image, "url").or_else(|| Some(image.trim().to_string()))
                })
        })
}

fn parse_entry_description(item: &str) -> String {
    xml_text(item, "content:encoded")
        .or_else(|| xml_text(item, "description"))
        .or_else(|| xml_text(item, "summary"))
        .or_else(|| xml_text(item, "itunes:subtitle"))
        .unwrap_or_default()
        .trim()
        .to_string()
}

fn find_feed_entry_audio_url(item: &str) -> Option<String> {
    static ENCLOSURE_RE: OnceLock<Regex> = OnceLock::new();
    let re = ENCLOSURE_RE.get_or_init(|| Regex::new(r#"(?is)<enclosure\b([^>]*)>"#).unwrap());
    for caps in re.captures_iter(item) {
        let attrs = caps.get(1).map(|m| m.as_str()).unwrap_or("");
        let mime = xml_attr(attrs, "type").unwrap_or_default().to_lowercase();
        if is_audio_mime_type(&mime) {
            if let Some(url) = xml_attr(attrs, "url") {
                return Some(url);
            }
        }
    }
    static LINK_RE: OnceLock<Regex> = OnceLock::new();
    let link_re = LINK_RE.get_or_init(|| Regex::new(r#"(?is)<link\b([^>]*)>"#).unwrap());
    for caps in link_re.captures_iter(item) {
        let attrs = caps.get(1).map(|m| m.as_str()).unwrap_or("");
        let mime = xml_attr(attrs, "type").unwrap_or_default().to_lowercase();
        if is_audio_mime_type(&mime) {
            if let Some(url) = xml_attr(attrs, "href") {
                return Some(url);
            }
        }
    }
    None
}

fn is_audio_mime_type(mime: &str) -> bool {
    matches!(
        mime,
        "audio/mpeg"
            | "audio/mp3"
            | "audio/x-mp3"
            | "audio/mpeg3"
            | "audio/mp4"
            | "audio/m4a"
            | "audio/x-m4a"
            | "audio/aac"
            | "audio/wav"
            | "audio/x-wav"
            | "audio/ogg"
            | "audio/opus"
            | "audio/flac"
    )
}

// Cache compiled regexes keyed by tag/attr name. Without this, every call to
// xml_text / extract_xml_blocks / xml_attr recompiles a regex; for a feed with
// hundreds of items that means thousands of compilations and dominates wall
// time of the refresh planner.
fn block_regex(tag: &str) -> &'static Regex {
    static CACHE: OnceLock<Mutex<HashMap<String, &'static Regex>>> = OnceLock::new();
    let cache = CACHE.get_or_init(|| Mutex::new(HashMap::new()));
    let mut guard = cache.lock().unwrap();
    if let Some(re) = guard.get(tag) {
        return re;
    }
    let pattern = format!(
        r"(?is)<{tag}\b[^>]*>(.*?)</{tag}>",
        tag = regex::escape(tag)
    );
    let leaked: &'static Regex = Box::leak(Box::new(Regex::new(&pattern).unwrap()));
    guard.insert(tag.to_string(), leaked);
    leaked
}

fn attr_regex(name: &str) -> &'static Regex {
    static CACHE: OnceLock<Mutex<HashMap<String, &'static Regex>>> = OnceLock::new();
    let cache = CACHE.get_or_init(|| Mutex::new(HashMap::new()));
    let mut guard = cache.lock().unwrap();
    if let Some(re) = guard.get(name) {
        return re;
    }
    let pattern = format!(
        r#"(?is)\b{}\s*=\s*("([^"]*)"|'([^']*)')"#,
        regex::escape(name)
    );
    let leaked: &'static Regex = Box::leak(Box::new(Regex::new(&pattern).unwrap()));
    guard.insert(name.to_string(), leaked);
    leaked
}

fn extract_xml_blocks(xml: &str, tag: &str) -> Vec<String> {
    block_regex(tag)
        .captures_iter(xml)
        .filter_map(|caps| caps.get(1).map(|m| m.as_str().to_string()))
        .collect()
}

fn xml_text(xml: &str, tag: &str) -> Option<String> {
    let raw = block_regex(tag)
        .captures(xml)?
        .get(1)?
        .as_str()
        .trim()
        .to_string();
    Some(decode_xml_text(&strip_cdata(&raw)))
}

fn parse_itunes_image_href(xml: &str) -> Option<String> {
    static IMAGE_RE: OnceLock<Regex> = OnceLock::new();
    let re = IMAGE_RE.get_or_init(|| Regex::new(r#"(?is)<itunes:image\b([^>]*)>"#).unwrap());
    let attrs = re.captures(xml)?.get(1)?.as_str();
    xml_attr(attrs, "href")
}

fn parse_media_thumbnail_url(xml: &str) -> Option<String> {
    static THUMB_RE: OnceLock<Regex> = OnceLock::new();
    let re = THUMB_RE.get_or_init(|| Regex::new(r#"(?is)<media:thumbnail\b([^>]*)>"#).unwrap());
    let attrs = re.captures(xml)?.get(1)?.as_str();
    xml_attr(attrs, "url")
}

fn xml_attr(attrs: &str, name: &str) -> Option<String> {
    let caps = attr_regex(name).captures(attrs)?;
    let value = caps
        .get(2)
        .or_else(|| caps.get(3))
        .map(|m| m.as_str())
        .unwrap_or("");
    Some(decode_xml_text(value))
}

fn strip_cdata(value: &str) -> String {
    let trimmed = value.trim();
    if trimmed.starts_with("<![CDATA[") && trimmed.ends_with("]]>") {
        trimmed
            .trim_start_matches("<![CDATA[")
            .trim_end_matches("]]>")
            .to_string()
    } else {
        trimmed.to_string()
    }
}

fn decode_xml_text(value: &str) -> String {
    value
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
        .replace("&apos;", "'")
}

fn parse_rfc2822_to_utc(value: &str) -> Option<String> {
    DateTime::parse_from_rfc2822(value)
        .ok()
        .map(|dt| dt.with_timezone(&Utc).to_rfc3339())
}

fn parse_duration_seconds_string(value: &str) -> Option<i64> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return None;
    }
    if let Ok(seconds) = trimmed.parse::<i64>() {
        return (seconds >= 0).then_some(seconds);
    }
    let parts: Vec<&str> = trimmed.split(':').collect();
    if !(2..=3).contains(&parts.len()) || parts.iter().any(|part| part.trim().is_empty()) {
        return None;
    }
    let nums: Vec<i64> = parts
        .iter()
        .map(|part| part.trim().parse::<i64>())
        .collect::<std::result::Result<Vec<_>, _>>()
        .ok()?;
    match nums.as_slice() {
        [minutes, seconds] if *minutes >= 0 && *seconds >= 0 => Some(minutes * 60 + seconds),
        [hours, minutes, seconds] if *hours >= 0 && *minutes >= 0 && *seconds >= 0 => {
            Some(hours * 3600 + minutes * 60 + seconds)
        }
        _ => None,
    }
}

fn release_date_prefix(value: &str) -> &str {
    value.split('T').next().unwrap_or(value)
}

fn open_readonly_sqlite(path: &Path) -> Result<Connection> {
    let conn = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .with_context(|| "failed to open sqlite database read-only")?;
    conn.busy_timeout(std::time::Duration::from_secs(30))?;
    conn.pragma_update(None, "query_only", true)?;
    Ok(conn)
}

fn query_posts(conn: &Connection, sql: &str, feed_id: [i64; 1]) -> Result<Vec<PostRow>> {
    let mut stmt = conn.prepare(sql)?;
    let rows = stmt.query_map(feed_id, post_from_row)?;
    Ok(rows.collect::<std::result::Result<Vec<PostRow>, _>>()?)
}

fn query_posts_with_limit(
    conn: &Connection,
    sql: &str,
    feed_id: i64,
    limit: i64,
) -> Result<Vec<PostRow>> {
    let mut stmt = conn.prepare(sql)?;
    let rows = stmt.query_map((feed_id, limit), post_from_row)?;
    Ok(rows.collect::<std::result::Result<Vec<PostRow>, _>>()?)
}

fn post_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<PostRow> {
    Ok(PostRow {
        feed_title: row.get(0)?,
        title: row.get(1)?,
        guid: row.get(2)?,
        processed_audio_path: row.get(3)?,
        description: row.get(4)?,
        release_date: row.get(5)?,
        duration: get_duration_seconds(row, 6)?,
        image_url: row.get(7)?,
        chapter_data: row.get(8)?,
    })
}

fn build_rss_xml(args: RssBuildArgs<'_>) -> String {
    let mut xml = String::from("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n");
    xml.push_str("<rss version=\"2.0\" xmlns:itunes=\"http://www.itunes.com/dtds/podcast-1.0.dtd\" xmlns:content=\"http://purl.org/rss/1.0/modules/content/\">\n<channel>\n");
    push_text_element(&mut xml, "title", args.title);
    push_text_element(&mut xml, "link", args.link);
    push_text_element(
        &mut xml,
        "description",
        &normalize_feed_text(args.description),
    );
    push_text_element(&mut xml, "lastBuildDate", args.last_build_date);
    if let Some(image_url) = args.image_url {
        xml.push_str("<image>");
        push_text_element(&mut xml, "url", image_url);
        push_text_element(&mut xml, "title", args.image_title);
        push_text_element(&mut xml, "link", args.link);
        xml.push_str("</image>\n");
    }
    for post in args.posts {
        push_item(
            &mut xml,
            post,
            args.base_url,
            args.feed_token,
            args.feed_secret,
            args.prepend_feed_title,
        );
    }
    xml.push_str("</channel>\n</rss>\n");
    xml
}

fn push_item(
    xml: &mut String,
    post: &PostRow,
    base_url: &str,
    feed_token: Option<&str>,
    feed_secret: Option<&str>,
    prepend_feed_title: bool,
) {
    xml.push_str("<item>");
    let title = if prepend_feed_title {
        match &post.feed_title {
            Some(feed_title) => format!("[{feed_title}] {}", post.title),
            None => post.title.clone(),
        }
    } else {
        post.title.clone()
    };
    push_text_element(xml, "title", &title);
    let audio_url = append_feed_token(
        &format!("{}/post/{}.mp3", base_url.trim_end_matches('/'), post.guid),
        feed_token,
        feed_secret,
    );
    let description = build_description(post);
    push_cdata_element(xml, "content:encoded", &description);
    push_cdata_element(xml, "description", &description);
    xml.push_str(&format!(
        "<enclosure url=\"{}\" type=\"audio/mpeg\" length=\"{}\"></enclosure>",
        xml_escape(&audio_url),
        enclosure_len(post)
    ));
    push_text_element(xml, "guid", &post.guid);
    if let Some(release_date) = post.release_date.as_deref() {
        push_text_element(xml, "pubDate", &format_rfc2822(Some(release_date)));
    }
    if let Some(image_url) = post.image_url.as_deref() {
        xml.push_str(&format!(
            "<itunes:image href=\"{}\"></itunes:image>",
            xml_escape(image_url)
        ));
    }
    if let Some(duration) = post.duration {
        if duration >= 0 {
            push_text_element(xml, "itunes:duration", &format_duration(duration));
        }
    }
    xml.push_str("</item>\n");
}

fn enclosure_len(post: &PostRow) -> u64 {
    post.processed_audio_path
        .as_deref()
        .and_then(|path| fs::metadata(path).ok())
        .map(|metadata| metadata.len())
        .unwrap_or(0)
}

fn build_description(post: &PostRow) -> String {
    let mut parts = Vec::new();
    if let Some(description) = post.description.as_deref() {
        if !description.is_empty() {
            parts.push(normalize_feed_text(description));
        }
    }
    let chapters = render_chapters(post.chapter_data.as_deref());
    if !chapters.is_empty() {
        parts.push(chapters);
    }
    parts.join("\n")
}

fn render_chapters(raw: Option<&str>) -> String {
    let Some(raw) = raw else {
        return String::new();
    };
    let Ok(Value::Object(data)) = serde_json::from_str::<Value>(raw) else {
        return String::new();
    };
    let chapters = data
        .get("chapters_for_output")
        .or_else(|| data.get("chapters_kept"));
    let Some(Value::Array(chapters)) = chapters else {
        return String::new();
    };
    let mut parsed = Vec::new();
    for chapter in chapters {
        let Value::Object(chapter) = chapter else {
            continue;
        };
        let title = chapter
            .get("title")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim();
        if title.is_empty() {
            continue;
        }
        let start = chapter
            .get("start_time")
            .and_then(value_to_f64)
            .unwrap_or(0.0)
            .max(0.0);
        parsed.push((start, title.to_string()));
    }
    parsed.sort_by(|a, b| a.0.total_cmp(&b.0));
    if parsed.is_empty() {
        return String::new();
    }
    let items = parsed
        .into_iter()
        .map(|(start, title)| {
            format!(
                "<li>{} {}</li>",
                format_chapter_timestamp(start),
                html_escape(&title)
            )
        })
        .collect::<String>();
    format!("<p><strong>Podly Chapters</strong></p><ul>{items}</ul>")
}

fn append_feed_token(url: &str, token: Option<&str>, secret: Option<&str>) -> String {
    match (token, secret) {
        (Some(token), Some(secret)) if !token.is_empty() && !secret.is_empty() => {
            let separator = if url.contains('?') { '&' } else { '?' };
            format!(
                "{url}{separator}feed_token={}&feed_secret={}",
                urlencoding_simple(token),
                urlencoding_simple(secret)
            )
        }
        _ => url.to_string(),
    }
}

fn format_rfc2822(raw: Option<&str>) -> String {
    if let Some(raw) = raw {
        if let Ok(dt) = DateTime::parse_from_rfc3339(raw) {
            return dt.with_timezone(&Utc).to_rfc2822();
        }
        if let Ok(naive) = NaiveDateTime::parse_from_str(raw, "%Y-%m-%d %H:%M:%S%.f") {
            return DateTime::<Utc>::from_naive_utc_and_offset(naive, Utc).to_rfc2822();
        }
    }
    Utc::now().to_rfc2822()
}

fn format_duration(duration_seconds: i64) -> String {
    let total = duration_seconds.max(0);
    let hours = total / 3600;
    let minutes = (total % 3600) / 60;
    let seconds = total % 60;
    if hours > 0 {
        format!("{hours}:{minutes:02}:{seconds:02}")
    } else {
        format!("{minutes:02}:{seconds:02}")
    }
}

fn format_chapter_timestamp(seconds: f64) -> String {
    format_duration(seconds.max(0.0) as i64)
}

fn push_text_element(xml: &mut String, name: &str, value: &str) {
    xml.push_str(&format!("<{name}>{}</{name}>\n", xml_escape(value)));
}

fn push_cdata_element(xml: &mut String, name: &str, value: &str) {
    xml.push_str(&format!(
        "<{name}><![CDATA[{}]]></{name}>",
        value.replace("]]>", "]]]]><![CDATA[>")
    ));
}

fn normalize_feed_text(value: &str) -> String {
    value.replace('\u{00a0}', " ").replace(
        ['\u{200b}', '\u{200c}', '\u{200d}', '\u{2060}', '\u{feff}'],
        "",
    )
}

fn xml_escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

fn html_escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

fn urlencoding_simple(value: &str) -> String {
    value
        .bytes()
        .flat_map(|byte| match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                vec![byte as char]
            }
            _ => format!("%{byte:02X}").chars().collect(),
        })
        .collect()
}

fn value_to_i64(value: &Value) -> Option<i64> {
    match value {
        Value::Number(number) => number
            .as_i64()
            .or_else(|| number.as_u64().and_then(|value| i64::try_from(value).ok())),
        Value::String(text) => text.parse::<i64>().ok(),
        _ => None,
    }
}

fn value_to_f64(value: &Value) -> Option<f64> {
    match value {
        Value::Number(number) => number.as_f64(),
        Value::String(text) => text.parse::<f64>().ok(),
        _ => None,
    }
}

fn value_to_string(value: &Value) -> Option<String> {
    match value {
        Value::String(text) => Some(text.clone()),
        Value::Number(number) => Some(number.to_string()),
        Value::Bool(value) => Some(value.to_string()),
        _ => None,
    }
}

fn print_json<T: Serialize>(value: &T) -> Result<()> {
    println!("{}", serde_json::to_string(value)?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use rusqlite::params;

    #[test]
    fn merge_windows_sorts_and_coalesces_overlaps() {
        assert_eq!(
            merge_windows(vec![(300, 400), (100, 200), (180, 250), (500, 550)]),
            vec![(100, 250), (300, 400), (500, 550)]
        );
    }

    #[test]
    fn keep_segments_inverts_removed_windows() {
        assert_eq!(
            keep_segments(&[(100, 200), (300, 350)], 500),
            vec![(0, 100), (200, 300), (350, 500)]
        );
    }

    #[test]
    fn duration_and_chapter_timestamp_format_match_python_shape() {
        assert_eq!(format_duration(65), "01:05");
        assert_eq!(format_duration(3_665), "1:01:05");
        assert_eq!(format_chapter_timestamp(125.9), "02:05");
    }

    #[test]
    fn feed_token_url_appending_encodes_values() {
        assert_eq!(
            append_feed_token("https://podly.test/feed/1", Some("tok en"), Some("s&c")),
            "https://podly.test/feed/1?feed_token=tok%20en&feed_secret=s%26c"
        );
        assert_eq!(
            append_feed_token("https://podly.test/feed/1?x=1", Some("tok"), Some("sec")),
            "https://podly.test/feed/1?x=1&feed_token=tok&feed_secret=sec"
        );
    }

    #[test]
    fn render_chapters_prefers_output_chapters_and_escapes_titles() {
        let raw = r#"{
            "chapters_kept": [{"title": "ignored", "start_time": 0}],
            "chapters_for_output": [
                {"title": "B < C", "start_time": 65},
                {"title": "Intro", "start_time": 0}
            ]
        }"#;

        assert_eq!(
            render_chapters(Some(raw)),
            "<p><strong>Podly Chapters</strong></p><ul><li>00:00 Intro</li><li>01:05 B &lt; C</li></ul>"
        );
    }

    #[test]
    fn normalize_word_timestamps_stream_contract_matches_python_filtering() {
        let dir = tempfile::tempdir().unwrap();
        let input = dir.path().join("input.json");
        let output = dir.path().join("output.json");
        fs::write(
            &input,
            r#"[
                {"sequence_num": "2", "words": [
                    {"word": "hello", "start": "1.0", "end": "1.5", "score": "0.9"},
                    {"word": "drop", "start": 2.0, "end": 1.0}
                ]},
                {"sequence_num": 3, "words": []}
            ]"#,
        )
        .unwrap();

        normalize_word_timestamps(TranscriptNormalizeArgs {
            input,
            output: output.clone(),
        })
        .unwrap();

        let value: Value = serde_json::from_str(&fs::read_to_string(output).unwrap()).unwrap();
        assert_eq!(
            value,
            serde_json::json!([
                {"sequence_num": 2, "words": [
                    {"word": "hello", "start": 1.0, "end": 1.5, "score": 0.9}
                ]}
            ])
        );
    }

    #[test]
    fn feed_render_reads_sqlite_and_includes_expected_rss_bits() {
        let dir = tempfile::tempdir().unwrap();
        let db_path = dir.path().join("podly.sqlite");
        let audio_path = dir.path().join("episode.mp3");
        fs::write(&audio_path, b"audio-bytes").unwrap();
        let conn = Connection::open(&db_path).unwrap();
        conn.execute_batch(
            "CREATE TABLE feed (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                image_url TEXT,
                last_changed_at TEXT
            );
            CREATE TABLE post (
                id INTEGER PRIMARY KEY,
                feed_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                guid TEXT NOT NULL,
                processed_audio_path TEXT,
                description TEXT,
                release_date TEXT,
                duration INTEGER,
                image_url TEXT,
                chapter_data TEXT,
                whitelisted BOOLEAN NOT NULL DEFAULT 0
            );",
        )
        .unwrap();
        conn.execute(
            "INSERT INTO feed (id, title, description, image_url, last_changed_at)
             VALUES (1, 'Feed & One', 'Desc', 'https://img.test/feed.png', '2024-01-02 03:04:05')",
            [],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO post (feed_id, title, guid, processed_audio_path, description, release_date, duration, image_url, chapter_data, whitelisted)
             VALUES (1, 'Episode <One>', 'guid-1', ?1, '<p>Hello</p>', '2024-01-03 04:05:06', 65, 'https://img.test/ep.png', ?2, 1)",
            params![
                audio_path.to_string_lossy(),
                r#"{"chapters_for_output":[{"title":"Intro","start_time":0}]}"#
            ],
        )
        .unwrap();
        drop(conn);

        let xml = render_feed(FeedRenderArgs {
            db: db_path,
            feed_id: 1,
            base_url: "https://podly.test".to_string(),
            include_unprocessed: false,
            feed_token: Some("tok".to_string()),
            feed_secret: Some("sec".to_string()),
        })
        .unwrap()
        .xml;

        assert!(xml.contains("<title>[podly] Feed &amp; One</title>"));
        assert!(
            xml.contains("https://podly.test/post/guid-1.mp3?feed_token=tok&amp;feed_secret=sec")
        );
        assert!(xml.contains("<itunes:duration>01:05</itunes:duration>"));
        assert!(xml.contains("<p><strong>Podly Chapters</strong></p><ul><li>00:00 Intro</li></ul>"));
        assert!(xml.contains("length=\"11\""));
    }

    #[test]
    fn chapters_write_replaces_chap_and_ctoc_frames() {
        let dir = tempfile::tempdir().unwrap();
        let audio = dir.path().join("audio.mp3");
        let chapters_json = dir.path().join("chapters.json");
        let removed_json = dir.path().join("removed.json");
        fs::write(&audio, b"not-real-audio-but-id3-can-write-tags").unwrap();
        fs::write(
            &chapters_json,
            r#"[
                {"title":"Intro","start_time_ms":0,"end_time_ms":1000},
                {"title":"Next","start_time_ms":1000,"end_time_ms":2000}
            ]"#,
        )
        .unwrap();
        fs::write(&removed_json, "[]").unwrap();

        write_chapters(ChaptersWriteArgs {
            audio: audio.clone(),
            chapters_json,
            removed_windows_json: removed_json,
        })
        .unwrap();

        let tag = Tag::read_from_path(audio).unwrap();
        assert_eq!(tag.chapters().count(), 2);
        assert_eq!(tag.tables_of_contents().count(), 1);
    }

    #[test]
    fn chapters_read_returns_empty_without_chap_frames() {
        let dir = tempfile::tempdir().unwrap();
        let audio = dir.path().join("audio.mp3");
        fs::write(&audio, b"not-real-audio").unwrap();

        let response = read_chapters(ChaptersReadArgs { audio }).unwrap();

        assert!(response.chapters.is_empty());
    }

    #[test]
    fn chapters_read_reads_file_written_by_chapters_write() {
        let dir = tempfile::tempdir().unwrap();
        let audio = dir.path().join("audio.mp3");
        let chapters_json = dir.path().join("chapters.json");
        let removed_json = dir.path().join("removed.json");
        fs::write(&audio, b"not-real-audio-but-id3-can-write-tags").unwrap();
        fs::write(
            &chapters_json,
            r#"[
                {"title":"Sponsor","start_time_ms":1000,"end_time_ms":2000},
                {"title":"Intro","start_time_ms":0,"end_time_ms":1000}
            ]"#,
        )
        .unwrap();
        fs::write(&removed_json, "[]").unwrap();

        write_chapters(ChaptersWriteArgs {
            audio: audio.clone(),
            chapters_json,
            removed_windows_json: removed_json,
        })
        .unwrap();

        let response = read_chapters(ChaptersReadArgs { audio }).unwrap();

        assert_eq!(response.chapters.len(), 2);
        assert_eq!(response.chapters[0].element_id, "chp0");
        assert_eq!(response.chapters[0].title, "Intro");
        assert_eq!(response.chapters[0].start_time_ms, 0);
        assert_eq!(response.chapters[1].title, "Sponsor");
    }

    #[test]
    fn chapters_detect_filters_titles_case_insensitively() {
        let chapters = vec![
            ChapterResponseItem {
                element_id: "chp0".to_string(),
                title: "Intro".to_string(),
                start_time_ms: 0,
                end_time_ms: 1000,
            },
            ChapterResponseItem {
                element_id: "chp1".to_string(),
                title: "Sponsored Break".to_string(),
                start_time_ms: 1000,
                end_time_ms: 2500,
            },
        ];

        let filters = parse_filter_strings_csv(" sponsor, advertisement ,,");
        let (keep, remove) = filter_chapters_by_strings(chapters, &filters);

        assert_eq!(keep.len(), 1);
        assert_eq!(keep[0].title, "Intro");
        assert_eq!(remove.len(), 1);
        assert_eq!(remove[0].title, "Sponsored Break");
    }

    #[test]
    fn stats_render_reads_seeded_sqlite_and_shapes_response() {
        let dir = tempfile::tempdir().unwrap();
        let db_path = dir.path().join("podly.sqlite");
        let log_path = dir.path().join("app.log");
        fs::write(
            &log_path,
            "2026-05-08 12:00:00,000 INFO [job_status] post_guid=slash/guid job_id=job-1 step_name=Processing audio\n",
        )
        .unwrap();
        let conn = Connection::open(&db_path).unwrap();
        conn.execute_batch(
            "CREATE TABLE feed (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, ad_detection_strategy TEXT NOT NULL,
                chapter_filter_strings TEXT
            );
            CREATE TABLE post (
                id INTEGER PRIMARY KEY, feed_id INTEGER NOT NULL, guid TEXT NOT NULL,
                title TEXT NOT NULL, download_url TEXT NOT NULL, unprocessed_audio_path TEXT,
                processed_audio_path TEXT, release_date TEXT, duration REAL, whitelisted INTEGER NOT NULL,
                download_count INTEGER, chapter_data TEXT, bleep_windows TEXT, refined_ad_boundaries TEXT
            );
            CREATE TABLE model_call (
                id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL, first_segment_sequence_num INTEGER NOT NULL,
                last_segment_sequence_num INTEGER NOT NULL, model_name TEXT NOT NULL, prompt TEXT NOT NULL,
                response TEXT, timestamp TEXT, status TEXT NOT NULL, error_message TEXT, retry_attempts INTEGER
            );
            CREATE TABLE transcript_segment (
                id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL, sequence_num INTEGER NOT NULL,
                start_time REAL NOT NULL, end_time REAL NOT NULL, text TEXT NOT NULL, speaker_label TEXT
            );
            CREATE TABLE audio_segment (
                id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL, model_call_id INTEGER,
                label TEXT NOT NULL, start_time REAL NOT NULL, end_time REAL NOT NULL
            );
            CREATE TABLE identification (
                id INTEGER PRIMARY KEY, transcript_segment_id INTEGER NOT NULL, model_call_id INTEGER NOT NULL,
                confidence REAL, label TEXT NOT NULL
            );
            CREATE TABLE processing_job (
                id TEXT PRIMARY KEY, post_guid TEXT NOT NULL, created_at TEXT
            );",
        )
        .unwrap();
        conn.execute("INSERT INTO feed VALUES (1, 'Feed', 'llm', NULL)", [])
            .unwrap();
        conn.execute(
            "INSERT INTO post VALUES (
                1, 1, 'slash/guid', 'Episode', 'https://example.com/audio.mp3',
                '/tmp/in.mp3', '/tmp/out.mp3', '2026-05-08 12:00:00.000000',
                90.0, 1, 2, NULL,
                '[{\"start_time\":5.0,\"end_time\":6.0}]',
                '[{\"orig_start\":10.0,\"orig_end\":20.0,\"refined_start\":9.5,\"refined_end\":20.5}]'
            )",
            [],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO model_call VALUES (1, 1, 0, 1, 'model-a', 'prompt', 'response', '2026-05-08 12:00:01.000000', 'success', NULL, 2)",
            [],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO transcript_segment VALUES
                (1, 1, 0, 0.0, 8.0, 'content', 'A'),
                (2, 1, 1, 10.0, 20.0, 'visit example.com code SAVE now', 'B')",
            [],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO audio_segment VALUES (1, 1, NULL, 'music', 20.0, 21.0)",
            [],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO identification VALUES (1, 2, 1, 0.95, 'ad')",
            [],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO processing_job VALUES ('job-1', 'slash/guid', '2026-05-08 12:00:02')",
            [],
        )
        .unwrap();
        drop(conn);

        let payload = render_stats(StatsRenderArgs {
            db: db_path,
            post_guid: "slash/guid".to_string(),
            min_confidence: 0.8,
            min_ad_segment_separation_seconds: 60.0,
            enable_boundary_refinement: true,
            stats_debug: false,
            log_path,
            in_root: dir.path().join("in"),
            srv_root: dir.path().join("srv"),
        })
        .unwrap();
        let stats = payload.get("stats").unwrap();

        assert_eq!(stats["post"]["guid"], "slash/guid");
        assert_eq!(stats["post"]["release_date"], "2026-05-08T12:00:00");
        assert_eq!(stats["processing_stats"]["total_segments"], 2);
        assert_eq!(stats["processing_stats"]["ad_segments_count"], 1);
        assert_eq!(stats["model_calls"][0]["retry_count"], 1);
        assert_eq!(stats["related_logs"]["latest_job_id"], "job-1");
        assert_eq!(
            stats["related_logs"]["entries"].as_array().unwrap().len(),
            1
        );
    }

    #[test]
    fn feed_refresh_plan_shapes_new_existing_archive_and_guid_repair() {
        let dir = tempfile::tempdir().unwrap();
        let db_path = dir.path().join("podly.sqlite");
        let xml_path = dir.path().join("feed.xml");
        fs::write(
            &xml_path,
            r#"<?xml version="1.0" encoding="utf-8"?>
            <rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:content="http://purl.org/rss/1.0/modules/content/">
              <channel>
                <title>Feed</title>
                <image><url>https://img.test/new-feed.png</url></image>
                <item>
                  <title>New Episode</title>
                  <guid>new-guid</guid>
                  <pubDate>Fri, 08 May 2026 12:00:00 +0000</pubDate>
                  <content:encoded><![CDATA[<p>New desc</p>]]></content:encoded>
                  <itunes:duration>01:02:03</itunes:duration>
                  <itunes:image href="https://img.test/new-ep.png" />
                  <enclosure url="https://cdn.test/new.mp3" type="audio/mpeg" />
                </item>
                <item>
                  <title>Existing Updated</title>
                  <guid>existing-guid</guid>
                  <description>Changed desc</description>
                  <itunes:duration>321</itunes:duration>
                  <enclosure url="https://cdn.test/existing.mp3" type="audio/mpeg" />
                </item>
                <item>
                  <title>Repaired Guid</title>
                  <guid>corrected-guid</guid>
                  <description>Legacy desc</description>
                  <enclosure url="https://cdn.test/legacy.mp3" type="audio/mpeg" />
                </item>
                <item>
                  <title>Archive Episode</title>
                  <guid>archive-guid</guid>
                  <pubDate>Fri, 01 May 2020 12:00:00 +0000</pubDate>
                  <description>Old desc</description>
                  <enclosure url="https://cdn.test/archive.mp3" type="audio/mpeg" />
                </item>
              </channel>
            </rss>"#,
        )
        .unwrap();
        let conn = Connection::open(&db_path).unwrap();
        conn.execute_batch(
            "CREATE TABLE feed (
                id INTEGER PRIMARY KEY,
                image_url TEXT
            );
            CREATE TABLE post (
                id INTEGER PRIMARY KEY,
                feed_id INTEGER NOT NULL,
                guid TEXT NOT NULL,
                download_url TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                processed_audio_path TEXT,
                release_date TEXT,
                duration INTEGER,
                image_url TEXT
            );",
        )
        .unwrap();
        conn.execute(
            "INSERT INTO feed VALUES (1, 'https://img.test/old-feed.png')",
            [],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO post VALUES
                (1, 1, 'existing-guid', 'https://cdn.test/existing.mp3', 'Existing', 'Old desc', NULL, '2026-05-01T12:00:00+00:00', NULL, NULL),
                (2, 1, 'legacy-guid', 'https://cdn.test/legacy.mp3', 'Repaired Guid', 'Legacy desc', NULL, '2026-05-02T12:00:00+00:00', NULL, NULL)",
            [],
        )
        .unwrap();
        drop(conn);

        let plan = plan_feed_refresh(FeedRefreshPlanArgs {
            db: db_path,
            feed_id: 1,
            feed_xml: xml_path,
            auto_whitelist_new_posts: true,
        })
        .unwrap();

        assert_eq!(plan.updates["image_url"], "https://img.test/new-feed.png");
        assert_eq!(plan.new_posts.len(), 2);
        assert_eq!(plan.new_posts[0]["guid"], "new-guid");
        assert_eq!(plan.new_posts[0]["duration"], 3723);
        assert_eq!(plan.new_posts[0]["whitelisted"], true);
        assert_eq!(plan.new_posts[1]["guid"], "archive-guid");
        assert_eq!(plan.new_posts[1]["whitelisted"], false);

        assert_eq!(plan.existing_post_updates.len(), 2);
        assert_eq!(plan.existing_post_updates[0]["post_id"], 1);
        assert_eq!(plan.existing_post_updates[0]["title"], "Existing Updated");
        assert_eq!(plan.existing_post_updates[0]["description"], "Changed desc");
        assert_eq!(plan.existing_post_updates[0]["duration"], 321);
        assert_eq!(plan.existing_post_updates[1]["post_id"], 2);
        assert_eq!(plan.existing_post_updates[1]["guid"], "corrected-guid");
    }

    #[test]
    fn jobs_render_matches_python_route_shape_and_ordering() {
        let dir = tempfile::tempdir().unwrap();
        let db_path = dir.path().join("podly.sqlite");
        let conn = Connection::open(&db_path).unwrap();
        conn.execute_batch(
            "CREATE TABLE feed (id INTEGER PRIMARY KEY, title TEXT NOT NULL);
            CREATE TABLE post (
                id INTEGER PRIMARY KEY, feed_id INTEGER NOT NULL, guid TEXT NOT NULL, title TEXT NOT NULL
            );
            CREATE TABLE processing_job (
                id TEXT PRIMARY KEY, post_guid TEXT NOT NULL, status TEXT NOT NULL,
                current_step INTEGER, step_name TEXT, total_steps INTEGER,
                progress_percentage REAL, started_at TEXT, completed_at TEXT,
                error_message TEXT, created_at TEXT, stage_history TEXT
            );
            INSERT INTO feed VALUES (1, 'Feed');
            INSERT INTO post VALUES (1, 1, 'guid-1', 'Episode 1');
            INSERT INTO processing_job VALUES
                ('job-complete', 'guid-1', 'completed', 4, 'Done', 4, 100.0, NULL,
                    '2026-05-08 12:02:00', NULL, '2026-05-08 12:02:00',
                    'this is not valid json'),
                ('job-pending', 'guid-1', 'pending', 0, 'Queued', 4, 0.0, NULL, NULL, NULL,
                    '2026-05-08 12:01:00', NULL),
                ('job-running', 'missing-guid', 'running', 2, 'Work', 4, 50.0,
                    '2026-05-08 12:00:00', NULL, NULL, '2026-05-08 12:00:00',
                    '[{\"step\":0,\"step_name\":\"Queued\",\"started_at\":\"2026-05-08T12:00:00\"},{\"step\":2,\"step_name\":\"Work\",\"started_at\":\"2026-05-08T12:00:30\"}]');",
        )
        .unwrap();
        drop(conn);

        let active = render_jobs(
            JobsListArgs {
                db: db_path.clone(),
                limit: 10,
            },
            true,
        )
        .unwrap();
        let active_jobs = active["jobs"].as_array().unwrap();
        assert_eq!(active_jobs.len(), 2);
        assert_eq!(active_jobs[0]["job_id"], "job-running");
        assert_eq!(active_jobs[0]["priority"], 2);
        assert_eq!(active_jobs[0]["post_title"], Value::Null);
        // job-running has real JSON history; it must be surfaced as a parsed array.
        let running_history = active_jobs[0]["stage_history"].as_array().unwrap();
        assert_eq!(running_history.len(), 2);
        assert_eq!(running_history[0]["step"], 0);
        assert_eq!(running_history[0]["step_name"], "Queued");
        assert_eq!(running_history[0]["started_at"], "2026-05-08T12:00:00");
        assert_eq!(running_history[1]["step"], 2);
        assert_eq!(running_history[1]["started_at"], "2026-05-08T12:00:30");

        assert_eq!(active_jobs[1]["job_id"], "job-pending");
        assert_eq!(active_jobs[1]["feed_title"], "Feed");
        // job-pending has NULL stage_history; it must surface as an empty array,
        // not null, so the frontend can iterate without a guard.
        assert_eq!(
            active_jobs[1]["stage_history"],
            Value::Array(Vec::new())
        );

        let all = render_jobs(
            JobsListArgs {
                db: db_path,
                limit: 10,
            },
            false,
        )
        .unwrap();
        let all_jobs = all["jobs"].as_array().unwrap();
        assert_eq!(all_jobs.len(), 3);
        assert_eq!(all_jobs[2]["job_id"], "job-complete");
        assert_eq!(all_jobs[2]["completed_at"], "2026-05-08T12:02:00");
        // job-complete has garbage in the column; falling back to [] keeps the
        // listing healthy even if a row was written with malformed JSON.
        assert_eq!(
            all_jobs[2]["stage_history"],
            Value::Array(Vec::new())
        );
    }

    #[test]
    fn jobs_status_mirrors_python_build_run_status_snapshot_shape() {
        let dir = tempfile::tempdir().unwrap();
        let db_path = dir.path().join("podly.sqlite");
        let conn = Connection::open(&db_path).unwrap();
        conn.execute_batch(
            "CREATE TABLE jobs_manager_run (
                id TEXT PRIMARY KEY,
                status TEXT,
                trigger TEXT,
                started_at TEXT,
                completed_at TEXT,
                updated_at TEXT,
                counters_reset_at TEXT,
                context_json TEXT
            );
            CREATE TABLE processing_job (
                id TEXT PRIMARY KEY,
                jobs_manager_run_id TEXT,
                post_guid TEXT NOT NULL,
                status TEXT NOT NULL,
                current_step INTEGER,
                step_name TEXT,
                total_steps INTEGER,
                progress_percentage REAL,
                started_at TEXT,
                completed_at TEXT,
                error_message TEXT,
                created_at TEXT,
                stage_history TEXT
            );
            INSERT INTO jobs_manager_run VALUES (
                'jobs-manager-singleton', 'running', 'manual',
                '2026-05-08 12:00:00', NULL, '2026-05-08 12:00:30',
                '2026-05-08 12:00:00', '{\"last_trigger\":\"manual\"}'
            );
            INSERT INTO processing_job VALUES
                ('j1', 'jobs-manager-singleton', 'g1', 'running', 2, 'Work', 4, 50.0, '2026-05-08 12:00:00', NULL, NULL, '2026-05-08 12:00:00', NULL),
                ('j2', 'jobs-manager-singleton', 'g2', 'pending', 0, 'Queued', 4, 0.0, NULL, NULL, NULL, '2026-05-08 12:00:10', NULL),
                ('j3', 'jobs-manager-singleton', 'g3', 'completed', 4, 'Done', 4, 100.0, '2026-05-08 12:00:00', '2026-05-08 12:00:20', NULL, '2026-05-08 12:00:00', NULL),
                ('j4', 'jobs-manager-singleton', 'g4', 'skipped', 4, 'Skipped', 4, 100.0, NULL, '2026-05-08 12:00:25', NULL, '2026-05-08 12:00:00', NULL),
                ('j5', 'jobs-manager-singleton', 'g5', 'failed', 2, 'Failed', 4, 50.0, '2026-05-08 12:00:00', '2026-05-08 12:00:15', 'boom', '2026-05-08 12:00:00', NULL),
                ('j6', 'jobs-manager-singleton', 'g6', 'cancelled', 0, 'Cancelled', 4, 0.0, NULL, '2026-05-08 12:00:18', 'stopped', '2026-05-08 12:00:00', NULL),
                ('j7', 'other-run', 'g7', 'running', 1, 'Work', 4, 25.0, NULL, NULL, NULL, '2026-05-08 12:00:00', NULL),
                ('j8', 'jobs-manager-singleton', 'g8', 'pending', 0, 'Queued', 4, 0.0, NULL, NULL, NULL, '2026-05-08 11:59:00', NULL);",
        )
        .unwrap();
        drop(conn);

        let response = render_jobs_status(JobsStatusArgs { db: db_path.clone() }).unwrap();
        let run = response["run"].as_object().unwrap();
        assert_eq!(run["id"], "jobs-manager-singleton");
        // running > 0 → status "running"; idle override only kicks in when
        // queued + running == 0.
        assert_eq!(run["status"], "running");
        assert_eq!(run["trigger"], "manual");
        // started_at gets the ISO-ified version of the SQLite naive timestamp.
        assert_eq!(run["started_at"], "2026-05-08T12:00:00");
        assert_eq!(run["counters_reset_at"], "2026-05-08T12:00:00");
        // Only jobs scoped to this run AND created at/after counters_reset_at
        // count. j7 (other run) and j8 (older created_at) must be excluded.
        assert_eq!(run["queued_jobs"], 1);
        assert_eq!(run["running_jobs"], 1);
        assert_eq!(run["completed_jobs"], 1);
        // failed + cancelled are summed into failed_jobs.
        assert_eq!(run["failed_jobs"], 2);
        assert_eq!(run["skipped_jobs"], 1);
        assert_eq!(run["total_jobs"], 6);
        // (completed + skipped) / total * 100 = 2/6 * 100 ≈ 33.33
        assert!((run["progress_percentage"].as_f64().unwrap() - 33.33).abs() < 0.01);
        // context_json gets parsed back to a real object, not left as a string.
        assert_eq!(run["context"]["last_trigger"], "manual");
    }

    #[test]
    fn jobs_status_returns_null_envelope_when_singleton_row_missing() {
        let dir = tempfile::tempdir().unwrap();
        let db_path = dir.path().join("podly.sqlite");
        let conn = Connection::open(&db_path).unwrap();
        conn.execute_batch(
            "CREATE TABLE jobs_manager_run (
                id TEXT PRIMARY KEY, status TEXT, trigger TEXT,
                started_at TEXT, completed_at TEXT, updated_at TEXT,
                counters_reset_at TEXT, context_json TEXT
            );
            CREATE TABLE processing_job (
                id TEXT PRIMARY KEY, jobs_manager_run_id TEXT,
                post_guid TEXT NOT NULL, status TEXT NOT NULL,
                current_step INTEGER, step_name TEXT, total_steps INTEGER,
                progress_percentage REAL, started_at TEXT, completed_at TEXT,
                error_message TEXT, created_at TEXT, stage_history TEXT
            );",
        )
        .unwrap();
        drop(conn);

        let response = render_jobs_status(JobsStatusArgs { db: db_path }).unwrap();
        assert_eq!(response["run"], Value::Null);
    }

    #[test]
    fn jobs_status_idle_when_no_queued_or_running_jobs() {
        let dir = tempfile::tempdir().unwrap();
        let db_path = dir.path().join("podly.sqlite");
        let conn = Connection::open(&db_path).unwrap();
        conn.execute_batch(
            "CREATE TABLE jobs_manager_run (
                id TEXT PRIMARY KEY, status TEXT, trigger TEXT,
                started_at TEXT, completed_at TEXT, updated_at TEXT,
                counters_reset_at TEXT, context_json TEXT
            );
            CREATE TABLE processing_job (
                id TEXT PRIMARY KEY, jobs_manager_run_id TEXT,
                post_guid TEXT NOT NULL, status TEXT NOT NULL,
                current_step INTEGER, step_name TEXT, total_steps INTEGER,
                progress_percentage REAL, started_at TEXT, completed_at TEXT,
                error_message TEXT, created_at TEXT, stage_history TEXT
            );
            INSERT INTO jobs_manager_run VALUES (
                'jobs-manager-singleton', 'running', 'manual',
                '2026-05-08 12:00:00', NULL, '2026-05-08 12:00:30',
                '2026-05-08 12:00:00', NULL
            );
            INSERT INTO processing_job VALUES
                ('j1', 'jobs-manager-singleton', 'g1', 'completed', 4, 'Done', 4, 100.0,
                    '2026-05-08 12:00:00', '2026-05-08 12:00:20', NULL,
                    '2026-05-08 12:00:00', NULL);",
        )
        .unwrap();
        drop(conn);

        let response = render_jobs_status(JobsStatusArgs { db: db_path }).unwrap();
        let run = response["run"].as_object().unwrap();
        // No queued/running jobs left → idle override regardless of what
        // status the run row carries.
        assert_eq!(run["status"], "pending");
        assert_eq!(run["completed_jobs"], 1);
        assert_eq!(run["queued_jobs"], 0);
        assert_eq!(run["running_jobs"], 0);
        // 1/1 * 100 = 100.0
        assert!((run["progress_percentage"].as_f64().unwrap() - 100.0).abs() < 0.01);
    }
}
