from __future__ import annotations

from typing import Literal, TypeAlias, TypedDict


JSONPrimitive: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONPrimitive | dict[str, "JSONValue"] | list["JSONValue"]
JSONObject: TypeAlias = dict[str, JSONValue]
JSONArray: TypeAlias = list[JSONValue]

SlideRepresentation: TypeAlias = Literal[
    "bullet",
    "two_column",
    "timeline",
    "comparison",
    "process_flow",
    "metric_cards",
]

CartoonShortType: TypeAlias = Literal[
    "educational_explainer",
    "debate_discussion",
    "story_sketch",
    "news_brief",
    "product_pitch",
    "case_study",
]

CartoonOutputMode: TypeAlias = Literal[
    "dual",
    "shorts_9_16",
    "widescreen_16_9",
]

CartoonShotType: TypeAlias = Literal[
    "wide_establishing",
    "medium_two_shot",
    "close_single",
    "over_shoulder",
]

CartoonCameraMove: TypeAlias = Literal[
    "static",
    "push_in",
    "pull_out",
    "pan_left",
    "pan_right",
]

CartoonTransitionType: TypeAlias = Literal[
    "cut",
    "crossfade",
    "fade_black",
]

CartoonMood: TypeAlias = Literal[
    "neutral",
    "energetic",
    "tense",
    "warm",
    "inspiring",
]

CartoonTimelineSchemaVersion: TypeAlias = Literal[
    "v1",
    "v2",
]

CartoonQualityTier: TypeAlias = Literal[
    "auto",
    "light",
    "balanced",
    "high",
]

CartoonRenderStyle: TypeAlias = Literal[
    "scene",
    "character_showcase",
]

CartoonBackgroundStyle: TypeAlias = Literal[
    "auto",
    "scene",
    "chroma_green",
]

CartoonFidelityPreset: TypeAlias = Literal[
    "auto_profile",
    "hd_1080p30",
    "uhd_4k30",
]

CartoonShowcaseAvatarMode: TypeAlias = Literal[
    "auto",
    "cache_sprite",
    "procedural_presenter",
]

CartoonEaseType: TypeAlias = Literal[
    "linear",
    "ease_in",
    "ease_out",
    "ease_in_out",
]


class SlideContent(TypedDict, total=False):
    section: str
    title: str
    representation: SlideRepresentation
    layout_payload: dict[str, JSONValue]
    bullets: list[str]
    speaker_notes: str
    code_snippet: str
    code_language: str


class SlideShowPayload(TypedDict):
    slides: list[SlideContent]


class AudioSpeaker(TypedDict, total=False):
    name: str
    role: str
    voice: str


class DialogueTurn(TypedDict, total=False):
    speaker: str
    text: str


class VideoSlideScript(TypedDict, total=False):
    slide_index: int
    summary: str
    dialogue: list[DialogueTurn]
    estimated_duration_sec: float
    slide_title: str


class VideoVisualRef(TypedDict, total=False):
    slide_index: int
    representation: SlideRepresentation
    item_index: int
    code_line_start: int
    code_line_end: int


class VideoConversationTurn(TypedDict, total=False):
    turn_index: int
    speaker: str
    text: str
    slide_index: int
    start_ms: int
    end_ms: int
    estimated_duration_ms: int
    visual_ref: VideoVisualRef
    segment_ref: str
    mouth_cues: list[dict[str, JSONValue]]


class DialogueAudioSegment(TypedDict, total=False):
    segment_ref: str
    speaker: str
    start_ms: int
    end_ms: int
    duration_ms: int
    text: str
    cache_hit: bool


class VideoRenderProfile(TypedDict, total=False):
    profile_key: str
    width: int
    height: int
    fps: int
    avatar_scale: float
    animation_level: str
    gpu_available: bool
    gpu_memory_mb: int


class VideoConversationTimeline(TypedDict, total=False):
    turns: list[VideoConversationTurn]
    audio_segments: list[DialogueAudioSegment]
    total_duration_ms: int
    turn_count: int
    speaker_count: int
    generated_with: str


class VideoPayload(TypedDict, total=False):
    topic: str
    title: str
    slides: list[SlideContent]
    slide_scripts: list[VideoSlideScript]
    speakers: list[AudioSpeaker]
    speaker_roster: list[AudioSpeaker]
    narrative_style: str
    conversation_style: str
    video_template: str
    animation_style: str
    render_mode: Literal["avatar_conversation", "classic_slides"]
    conversation_timeline: VideoConversationTimeline
    visual_refs: list[VideoVisualRef]
    render_profile: VideoRenderProfile
    metadata: dict[str, JSONValue]


class CartoonCharacterSpec(TypedDict, total=False):
    id: str
    name: str
    role: str
    color_hex: str
    outfit_variant: str
    voice: str
    asset_mode: str
    lottie_source: str
    cache_root: str
    state_map: dict[str, JSONValue]
    anchor: dict[str, float]
    default_scale: float
    z_layer: int


class CartoonCameraKeyframe(TypedDict, total=False):
    t_ms: int
    x: float
    y: float
    zoom: float
    rotation: float
    ease: CartoonEaseType


class CartoonCameraTrack(TypedDict, total=False):
    keyframes: list[CartoonCameraKeyframe]


class CartoonCharacterKeyframe(TypedDict, total=False):
    t_ms: int
    x_norm: float
    y_norm: float
    scale: float
    rotation: float
    pose: str
    emotion: str
    opacity: float
    z_index: int
    ease: CartoonEaseType


class CartoonCharacterTrack(TypedDict, total=False):
    character_id: str
    keyframes: list[CartoonCharacterKeyframe]


class CartoonSubtitleTrack(TypedDict, total=False):
    y_norm: float
    max_lines: int
    style: str


class CartoonDialogueTurn(TypedDict, total=False):
    turn_index: int
    speaker_id: str
    speaker_name: str
    text: str
    emotion: str
    start_ms: int
    end_ms: int
    estimated_duration_ms: int


class CartoonScene(TypedDict, total=False):
    scene_index: int
    title: str
    hook: str
    background_key: str
    camera_preset: str
    shot_type: CartoonShotType
    camera_move: CartoonCameraMove
    transition_in: CartoonTransitionType
    transition_out: CartoonTransitionType
    mood: CartoonMood
    focus_character_id: str
    duration_ms: int
    turns: list[CartoonDialogueTurn]
    visual_notes: str
    camera_track: CartoonCameraTrack
    character_tracks: list[CartoonCharacterTrack]
    subtitle_track: CartoonSubtitleTrack


class CartoonTimeline(TypedDict, total=False):
    scenes: list[CartoonScene]
    total_duration_ms: int
    scene_count: int
    speaker_count: int
    generated_with: str


class CartoonRenderProfile(TypedDict, total=False):
    profile_key: str
    shorts_width: int
    shorts_height: int
    widescreen_width: int
    widescreen_height: int
    fps: int
    gpu_available: bool
    gpu_memory_mb: int
    animation_level: str


class CartoonOutputArtifact(TypedDict, total=False):
    key: str
    format: str
    status: str
    bytes: int
    path_hint: str
    mime: str


class CartoonPayload(TypedDict, total=False):
    topic: str
    title: str
    short_type: CartoonShortType
    output_mode: CartoonOutputMode
    language: str
    hinglish_script: bool
    character_roster: list[CartoonCharacterSpec]
    timeline: CartoonTimeline
    render_profile: CartoonRenderProfile
    output_artifacts: list[CartoonOutputArtifact]
    script_markdown: str
    metadata: dict[str, JSONValue]
    timeline_schema_version: CartoonTimelineSchemaVersion
    quality_tier: CartoonQualityTier
    render_style: CartoonRenderStyle
    background_style: CartoonBackgroundStyle
    fidelity_preset: CartoonFidelityPreset
    showcase_avatar_mode: CartoonShowcaseAvatarMode


class AssetSection(TypedDict, total=False):
    kind: str
    key: str
    title: str
    data: JSONValue
    mime: str | None
    optional: bool


class AssetArtifactEnvelope(TypedDict, total=False):
    intent: str
    title: str
    summary: str
    sections: list[AssetSection]
    attachments: dict[str, JSONValue]
    metrics: dict[str, JSONValue]
    provenance: dict[str, JSONValue]


class ToolDependencySpec(TypedDict, total=False):
    requires_artifacts: list[str]
    produces_artifacts: list[str]
    optional_requires: list[str]


class ToolExecutionSpec(TypedDict, total=False):
    intent: str
    tool_key: str
    stage_profile: str
    requirements_schema_key: str
    verify_profile: str
    verify_required: bool
    execution_policy: "ToolExecutionPolicy"
    dependency: ToolDependencySpec


class VerificationIssue(TypedDict, total=False):
    code: str
    severity: str
    message: str
    path: str


class VerificationSummary(TypedDict, total=False):
    status: str
    issues: list[VerificationIssue]
    checks_run: list[str]


class StageExecutionRecord(TypedDict, total=False):
    run_id: str
    tool_key: str
    intent: str
    stage_key: str
    attempt: int
    status: str
    started_at: str
    ended_at: str
    duration_ms: int
    error_code: str
    message: str


class AssetRunSummary(TypedDict, total=False):
    run_id: str
    workflow_key: str
    tool_key: str
    intent: str
    status: str
    verification_status: str
    retry_count: int


class ToolExecutionPolicy(TypedDict, total=False):
    timeout_ms: int | None
    max_retries: int
    retry_backoff_ms: list[int]
    fail_policy: str
    concurrency_group: str | None
    profile: str


class ArtifactSchemaRef(TypedDict, total=False):
    intent: str
    version: str
    id: str


class ToolPluginSpec(TypedDict, total=False):
    plugin_key: str
    intent: str
    title: str
    description: str
    capabilities: list[str]
    execution_spec: ToolExecutionSpec
    schema_ref: ArtifactSchemaRef


class WorkflowPluginSpec(TypedDict, total=False):
    workflow_key: str
    title: str
    description: str
    tool_keys: list[str]
    tool_dependencies: dict[str, list[str]]


OrchestrationState: TypeAlias = Literal[
    "pending",
    "ready",
    "running",
    "blocked",
    "completed",
    "failed",
    "skipped",
]


class ToolScaffoldSpec(TypedDict, total=False):
    intent: str
    title: str
    description: str
    asset_kind: str
    depends_on: list[str]
    produces: list[str]


class SimulationNodeResult(TypedDict, total=False):
    tool_key: str
    intent: str
    planned_state_path: list[str]
    blocked_by: list[str]
    expected_stages: list[str]


class SimulationReport(TypedDict, total=False):
    workflow_key: str
    run_id: str
    nodes: list[SimulationNodeResult]
    notes: list[str]


class StageDiagnostic(TypedDict, total=False):
    run_id: str
    workflow_key: str
    tool_key: str
    intent: str
    stage_key: str
    attempt: int
    status: str
    error_code: str
    message: str
    duration_ms: int
    started_at: str
    ended_at: str
    from_state: str
    to_state: str
    transition_valid: bool


class RunLedgerRecord(TypedDict, total=False):
    run_id: str
    workflow_key: str
    planner_mode: str
    status: str
    started_at: str
    ended_at: str
    tool_summaries: list[AssetRunSummary]
    error_counts: dict[str, int]


class TelemetryContextPayload(TypedDict, total=False):
    request_id: str
    session_id: str
    run_id: str
    job_id: str
    trace_id: str
    span_id: str


class ObservabilityEventPayload(TypedDict, total=False):
    event_name: str
    component: str
    status: str
    timestamp: str
    attributes: dict[str, JSONValue]
    payload_ref: str


class MindMapNode(TypedDict, total=False):
    name: str
    children: list["MindMapNode"]


MindMapPayload: TypeAlias = MindMapNode


class FlashcardItem(TypedDict, total=False):
    question: str
    short_answer: str


class FlashcardsPayload(TypedDict, total=False):
    topic: str
    cards: list[FlashcardItem]


DataTableCell: TypeAlias = JSONPrimitive
DataTableRow: TypeAlias = dict[str, DataTableCell]


class DataTablePayload(TypedDict, total=False):
    topic: str
    columns: list[str]
    rows: list[DataTableRow]


class QuizQuestion(TypedDict, total=False):
    question: str
    options: list[str]
    correct_index: int
    correct_option_index: int


class QuizPayload(TypedDict, total=False):
    topic: str
    questions: list[QuizQuestion]


class QuizHistoryEntry(TypedDict, total=False):
    id: str
    topic: str
    difficulty: str
    constraints: str
    model: str
    created_at: str
    quiz: QuizPayload


class QuizHistoryStorePayload(TypedDict):
    quizzes: list[QuizHistoryEntry]


class AudioOverviewPayload(TypedDict, total=False):
    topic: str
    title: str
    summary: str
    speakers: list[AudioSpeaker]
    dialogue: list[DialogueTurn]


class IntentPayload(TypedDict, total=False):
    topic: str
    additional_instructions: str
    constraints: str
    notes: str
    additional_notes: str
    question_count: int
    card_count: int
    row_count: int
    subtopic_count: int
    slides_per_subtopic: int
    max_depth: int
    speaker_count: int
    turn_count: int
    difficulty: str
    format_key: str
    code_mode: str
    conversation_style: str
    language: str
    slow_audio: bool
    video_template: str
    youtube_prompt: bool
    animation_style: str
    representation_mode: str
    short_type: str
    scene_count: int
    output_mode: str
    hinglish_script: bool
    timeline_schema_version: str
    quality_tier: str
    render_style: str
    background_style: str
    fidelity_preset: str
    showcase_avatar_mode: str
    idea: str
    manual_timeline_json: str


IntentPayloadMap: TypeAlias = dict[str, IntentPayload]


class AgentDashboardSessionEntry(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    title: str
    planner_mode: str
    active_topic: str
    recent_topics: list[JSONValue]
    pending_plan: JSONValue
    history: list[JSONValue]


class AgentDashboardSessionStorePayload(TypedDict):
    sessions: list[AgentDashboardSessionEntry]


ChatMessage: TypeAlias = dict[str, JSONValue]
ChatHistory: TypeAlias = list[ChatMessage]
ArtifactMap: TypeAlias = dict[str, JSONValue]


RequirementFieldType: TypeAlias = Literal["text", "int", "enum", "bool"]
RequirementFieldValue: TypeAlias = str | int | bool


class RequirementFieldSpec(TypedDict, total=False):
    label: str
    type: RequirementFieldType
    default: RequirementFieldValue
    options: list[str]
    min: int
    max: int
    step: int


class IntentRequirementSpec(TypedDict, total=False):
    mandatory: list[str]
    optional: dict[str, RequirementFieldSpec]
    requirements_schema_key: str
    schema_version: str


RequirementSpecMap: TypeAlias = dict[str, IntentRequirementSpec]
