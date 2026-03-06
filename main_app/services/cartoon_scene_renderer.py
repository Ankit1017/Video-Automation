from __future__ import annotations

import math
from typing import Any, cast

from main_app.contracts import CartoonCharacterSpec, CartoonDialogueTurn, CartoonScene
from main_app.services.cartoon_subtitle_service import CartoonSubtitleService


class CartoonSceneRenderer:
    def __init__(self, subtitle_service: CartoonSubtitleService | None = None) -> None:
        self._subtitle_service = subtitle_service or CartoonSubtitleService()

    def render_frame(
        self,
        *,
        image_module: Any,
        draw_module: Any,
        font_module: Any,
        width: int,
        height: int,
        topic: str,
        scene: CartoonScene,
        active_turn: CartoonDialogueTurn | None,
        active_mouth: str = "",
        character_roster: list[CartoonCharacterSpec],
        frame_index: int = 0,
        frame_count: int = 1,
        cinematic_mode: bool = True,
        frame_plan: dict[str, object] | None = None,
        lottie_cache_service: Any | None = None,
        flat_asset_sprite_service: Any | None = None,
        timeline_schema_version: str = "v1",
        render_style: str = "scene",
        background_style: str = "scene",
        showcase_avatar_mode: str = "cache_sprite",
    ) -> Any:
        safe_frame_count = max(1, int(frame_count))
        safe_frame_index = max(0, min(int(frame_index), safe_frame_count - 1))
        progress = 0.0 if safe_frame_count <= 1 else safe_frame_index / float(safe_frame_count - 1)
        if not cinematic_mode:
            progress = 0.0

        style = _resolve_render_style(render_style)
        showcase_mode = style == "character_showcase"
        bg_mode = _resolve_background_style(background_style, render_style=style)
        chroma_mode = bg_mode == "chroma_green"

        image = image_module.new(
            "RGB",
            (width, height),
            color=((0, 255, 0) if chroma_mode else self._background_color(scene.get("background_key"))),
        )
        drawer = draw_module.Draw(image)

        use_v2_plan = _clean(timeline_schema_version).lower() == "v2" and isinstance(frame_plan, dict)
        if use_v2_plan:
            planned_camera = frame_plan.get("camera", {})
            camera_map = planned_camera if isinstance(planned_camera, dict) else {}
            camera_shift_x = _float_safe(camera_map.get("x"), default=0.0)
            camera_shift_y = _float_safe(camera_map.get("y"), default=0.0)
            camera_zoom = max(0.2, _float_safe(camera_map.get("zoom"), default=1.0))
        else:
            camera_shift_x, camera_shift_y, camera_zoom = _camera_transform(
                camera_move=(_clean(scene.get("camera_move")).lower() if cinematic_mode else "static"),
                progress=progress,
            )

        if not chroma_mode:
            self._draw_background_layers(
                drawer=drawer,
                width=width,
                height=height,
                scene=scene,
                progress=progress,
                camera_shift_x=camera_shift_x,
                camera_shift_y=camera_shift_y,
                camera_zoom=camera_zoom,
            )
        if not showcase_mode and not chroma_mode:
            self._draw_header(
                drawer=drawer,
                font_module=font_module,
                width=width,
                topic=topic,
                scene_title=_clean(scene.get("title")) or "Scene",
                mood=_clean(scene.get("mood")) or "neutral",
                frame_bob=_sin_like(progress, period=0.5),
            )
        if use_v2_plan:
            self._draw_characters_from_plan(
                image=image,
                image_module=image_module,
                drawer=drawer,
                width=width,
                height=height,
                font_module=font_module,
                character_roster=character_roster,
                frame_plan=cast(dict[str, object], frame_plan),
                lottie_cache_service=lottie_cache_service,
                flat_asset_sprite_service=flat_asset_sprite_service,
                camera_shift_x=camera_shift_x,
                camera_shift_y=camera_shift_y,
                camera_zoom=camera_zoom,
                render_style=style,
                showcase_avatar_mode=showcase_avatar_mode,
            )
        else:
            if showcase_mode:
                self._draw_characters(
                    drawer=drawer,
                    width=width,
                    height=height,
                    font_module=font_module,
                    character_roster=character_roster,
                    active_speaker_id=_clean((active_turn or {}).get("speaker_id")),
                    active_mouth=active_mouth,
                    shot_type="close_single",
                    focus_character_id=_clean(scene.get("focus_character_id")),
                    frame_index=safe_frame_index,
                    progress=progress,
                    camera_shift_x=0.0,
                    camera_shift_y=0.0,
                    camera_zoom=max(1.0, camera_zoom),
                )
            else:
                self._draw_characters(
                    drawer=drawer,
                    width=width,
                    height=height,
                    font_module=font_module,
                    character_roster=character_roster,
                    active_speaker_id=_clean((active_turn or {}).get("speaker_id")),
                    active_mouth=active_mouth,
                    shot_type=_clean(scene.get("shot_type")) or "medium_two_shot",
                    focus_character_id=_clean(scene.get("focus_character_id")),
                    frame_index=safe_frame_index,
                    progress=progress,
                    camera_shift_x=camera_shift_x,
                    camera_shift_y=camera_shift_y,
                    camera_zoom=camera_zoom,
                )
        if not showcase_mode or _showcase_subtitle_enabled(frame_plan=frame_plan):
            self._draw_subtitle(
                drawer=drawer,
                width=width,
                height=height,
                font_module=font_module,
                active_turn=active_turn,
                character_roster=character_roster,
                progress=progress,
            )

        if not chroma_mode:
            image = self._apply_grade(
                image_module=image_module,
                image=image,
                mood=_clean(scene.get("mood")) or "neutral",
            )
        if cinematic_mode and not showcase_mode and not chroma_mode:
            image = self._apply_transition_overlay(
                image_module=image_module,
                image=image,
                transition_in=_clean(scene.get("transition_in")) or "cut",
                transition_out=_clean(scene.get("transition_out")) or "cut",
                progress=progress,
            )
        return image

    @staticmethod
    def _background_color(background_key: object) -> tuple[int, int, int]:
        key = _clean(background_key).lower()
        mapping = {
            "studio_blue": (20, 30, 55),
            "classroom_warm": (49, 37, 24),
            "city_evening": (32, 28, 48),
            "news_desk": (26, 26, 31),
            "product_stage": (31, 20, 39),
            "case_boardroom": (21, 32, 30),
        }
        return mapping.get(key, (22, 29, 44))

    def _draw_background_layers(
        self,
        *,
        drawer: Any,
        width: int,
        height: int,
        scene: CartoonScene,
        progress: float,
        camera_shift_x: float,
        camera_shift_y: float,
        camera_zoom: float,
    ) -> None:
        bg = self._background_color(scene.get("background_key"))
        sky_top = tuple(max(channel - 20, 0) for channel in bg)
        sky_bottom = tuple(min(channel + 35, 255) for channel in bg)
        for stripe in range(0, max(1, height // 24)):
            y0 = stripe * 24
            mix = stripe / float(max(1, height // 24))
            color = (
                int(sky_top[0] + (sky_bottom[0] - sky_top[0]) * mix),
                int(sky_top[1] + (sky_bottom[1] - sky_top[1]) * mix),
                int(sky_top[2] + (sky_bottom[2] - sky_top[2]) * mix),
            )
            drawer.rectangle((0, y0, width, min(height, y0 + 24)), fill=color)

        horizon = int(height * (0.56 - (camera_zoom - 1.0) * 0.08))
        drawer.rectangle((0, horizon, width, height), fill=(18, 23, 33))

        base_parallax = _sin_like(progress, period=1.0) * 12.0
        far_shift = int((camera_shift_x * 0.35) + (base_parallax * 0.35))
        mid_shift = int((camera_shift_x * 0.65) + (base_parallax * 0.7))
        near_shift = int((camera_shift_x * 1.1) + (base_parallax * 1.2))
        cam_y = int(camera_shift_y)

        for block in range(-2, 12):
            x = (block * 140) + far_shift
            h = 110 + ((block % 3) * 18)
            drawer.rectangle((x, horizon - h + cam_y, x + 86, horizon + cam_y), fill=(35, 45, 70))
        for block in range(-2, 10):
            x = (block * 180) + mid_shift + 42
            h = 80 + ((block % 4) * 14)
            drawer.rectangle((x, horizon - h + 18 + cam_y, x + 110, horizon + 40 + cam_y), fill=(40, 55, 86))
        for block in range(-2, 8):
            x = (block * 230) + near_shift + 26
            h = 64 + ((block % 2) * 18)
            drawer.rounded_rectangle(
                (x, horizon - h + 44 + cam_y, x + 136, horizon + 92 + cam_y),
                radius=12,
                fill=(58, 74, 112),
            )

    def _draw_header(
        self,
        *,
        drawer: Any,
        font_module: Any,
        width: int,
        topic: str,
        scene_title: str,
        mood: str,
        frame_bob: float,
    ) -> None:
        title_font = _font(font_module=font_module, size=36, bold=True)
        topic_font = _font(font_module=font_module, size=22, bold=False)
        mood_text = mood.replace("_", " ").title()
        y_offset = int(frame_bob * 3.0)
        drawer.text((28, 16 + y_offset), scene_title, fill=(248, 250, 255), font=title_font)
        drawer.text((28, 62 + y_offset), _clean(topic), fill=(205, 221, 248), font=topic_font)
        drawer.text((width - 220, 24 + y_offset), f"Mood: {mood_text}", fill=(188, 209, 236), font=topic_font)
        drawer.line((24, 100 + y_offset, width - 24, 100 + y_offset), fill=(78, 112, 158), width=2)

    def _draw_characters(
        self,
        *,
        drawer: Any,
        width: int,
        height: int,
        font_module: Any,
        character_roster: list[CartoonCharacterSpec],
        active_speaker_id: str,
        active_mouth: str,
        shot_type: str,
        focus_character_id: str,
        frame_index: int,
        progress: float,
        camera_shift_x: float,
        camera_shift_y: float,
        camera_zoom: float,
    ) -> None:
        roster = [item for item in character_roster if isinstance(item, dict)]
        if not roster:
            roster = [
                {"id": "speaker_a", "name": "Speaker A", "color_hex": "#4F8EF7"},
                {"id": "speaker_b", "name": "Speaker B", "color_hex": "#5BC0A8"},
            ]
        count = max(2, min(len(roster), 4))
        name_font = _font(font_module=font_module, size=max(18, int(min(width, height) * 0.022)), bold=True)

        base_radius = int(min(width, height) * 0.078)
        if shot_type == "close_single":
            base_radius = int(base_radius * 1.28)
        elif shot_type == "wide_establishing":
            base_radius = int(base_radius * 0.88)

        if shot_type == "close_single":
            active_index = _find_character_index(roster, active_speaker_id or focus_character_id)
            if active_index < 0:
                active_index = 0
            indices = [active_index] + [idx for idx in range(count) if idx != active_index][:1]
        else:
            indices = list(range(count))

        span = int(width * 0.68)
        start_x = int(width * 0.16)
        gap = int(span / max(1, len(indices) - 1))
        base_y = int(height * 0.68)
        motion_wave = _sin_like(progress, period=0.42)

        for slot, idx in enumerate(indices):
            character = roster[idx] if idx < len(roster) else roster[-1]
            char_id = _clean(character.get("id"))
            name = _clean(character.get("name")) or f"Speaker {slot + 1}"
            center_x = start_x + (gap * slot)
            center_y = base_y

            center_x += int(camera_shift_x * 0.95)
            center_y += int(camera_shift_y * 0.95)

            if shot_type == "over_shoulder" and slot == 0:
                center_x = int(width * 0.22 + camera_shift_x * 0.8)
                center_y = int(height * 0.72 + camera_shift_y)
            if shot_type == "over_shoulder" and slot == 1:
                center_x = int(width * 0.72 + camera_shift_x * 0.7)
                center_y = int(height * 0.64 + camera_shift_y * 0.8)

            rgb = _hex_to_rgb(_clean(character.get("color_hex"))) or (95, 140, 210)
            is_active = bool(active_speaker_id and char_id == active_speaker_id)

            actor_zoom = camera_zoom * (1.08 if is_active else 1.0)
            rr = max(22, int(base_radius * actor_zoom))
            lift = int(rr * (0.12 if is_active else 0.04) + motion_wave * 3.0)

            outline = (245, 247, 255) if is_active else (186, 198, 218)
            outline_width = 6 if is_active else 3
            drawer.ellipse(
                (center_x - rr, center_y - rr - lift, center_x + rr, center_y + rr - lift),
                fill=rgb,
                outline=outline,
                width=outline_width,
            )

            blink = frame_index % 47 in {0, 1}
            eye_y = center_y - int(rr * 0.2) - lift
            eye_dx = int(rr * 0.28)
            eye_r = max(2, int(rr * 0.07))
            if blink:
                drawer.line(
                    (center_x - eye_dx - eye_r, eye_y, center_x - eye_dx + eye_r, eye_y),
                    fill=(18, 24, 34),
                    width=2,
                )
                drawer.line(
                    (center_x + eye_dx - eye_r, eye_y, center_x + eye_dx + eye_r, eye_y),
                    fill=(18, 24, 34),
                    width=2,
                )
            else:
                drawer.ellipse(
                    (center_x - eye_dx - eye_r, eye_y - eye_r, center_x - eye_dx + eye_r, eye_y + eye_r),
                    fill=(18, 24, 34),
                )
                drawer.ellipse(
                    (center_x + eye_dx - eye_r, eye_y - eye_r, center_x + eye_dx + eye_r, eye_y + eye_r),
                    fill=(18, 24, 34),
                )

            mouth_center_y = center_y + int(rr * 0.18) - lift
            mouth_w = int(rr * (0.55 if is_active else 0.34))
            if is_active:
                viseme = _clean(active_mouth).upper()
                if viseme:
                    viseme_open = _viseme_open_ratio(viseme)
                    mouth_h = max(2, int(rr * viseme_open))
                    if viseme == "X":
                        drawer.line(
                            (center_x - mouth_w // 2, mouth_center_y, center_x + mouth_w // 2, mouth_center_y),
                            fill=(18, 22, 32),
                            width=3,
                        )
                    else:
                        drawer.ellipse(
                            (
                                center_x - mouth_w // 2,
                                mouth_center_y - mouth_h // 2,
                                center_x + mouth_w // 2,
                                mouth_center_y + mouth_h // 2,
                            ),
                            fill=(15, 18, 28),
                        )
                else:
                    mouth_phase = (frame_index // 2) % 4
                    mouth_h = max(2, int(rr * (0.05 + (mouth_phase * 0.03))))
                    drawer.ellipse(
                        (
                            center_x - mouth_w // 2,
                            mouth_center_y - mouth_h // 2,
                            center_x + mouth_w // 2,
                            mouth_center_y + mouth_h // 2,
                        ),
                        fill=(15, 18, 28),
                    )
            else:
                drawer.line(
                    (center_x - mouth_w // 2, mouth_center_y, center_x + mouth_w // 2, mouth_center_y),
                    fill=(20, 26, 38),
                    width=3,
                )

            bbox = drawer.textbbox((0, 0), name, font=name_font)
            text_w = max(0, bbox[2] - bbox[0])
            drawer.text((center_x - text_w // 2, center_y + rr + 12 - lift), name, fill=(242, 246, 255), font=name_font)

    def _draw_characters_from_plan(
        self,
        *,
        image: Any,
        image_module: Any,
        drawer: Any,
        width: int,
        height: int,
        font_module: Any,
        character_roster: list[CartoonCharacterSpec],
        frame_plan: dict[str, object],
        lottie_cache_service: Any | None,
        flat_asset_sprite_service: Any | None,
        camera_shift_x: float,
        camera_shift_y: float,
        camera_zoom: float,
        render_style: str,
        showcase_avatar_mode: str,
    ) -> None:
        planned_raw = frame_plan.get("characters", [])
        planned = [item for item in planned_raw if isinstance(item, dict)] if isinstance(planned_raw, list) else []
        if not planned:
            self._draw_characters(
                drawer=drawer,
                width=width,
                height=height,
                font_module=font_module,
                character_roster=character_roster,
                active_speaker_id="",
                active_mouth="",
                shot_type="medium_two_shot",
                focus_character_id="",
                frame_index=0,
                progress=0.0,
                camera_shift_x=camera_shift_x,
                camera_shift_y=camera_shift_y,
                camera_zoom=camera_zoom,
            )
            return
        showcase_mode = _resolve_render_style(render_style) == "character_showcase"
        avatar_mode = _resolve_showcase_avatar_mode(showcase_avatar_mode, showcase_mode=showcase_mode)
        if showcase_mode:
            planned = [_showcase_subject(planned)]
        roster_by_id = {
            _clean(item.get("id")).lower(): item
            for item in character_roster
            if isinstance(item, dict) and _clean(item.get("id"))
        }
        name_font = _font(font_module=font_module, size=max(18, int(min(width, height) * 0.022)), bold=True)

        for planned_character in sorted(planned, key=lambda item: _int_safe(item.get("z_index"), default=0)):
            char_id = _clean(planned_character.get("character_id")).lower()
            character = roster_by_id.get(char_id, {})
            name = _clean(planned_character.get("name")) or _clean(character.get("name")) or "Speaker"
            x_norm = _float_safe(planned_character.get("x_norm"), default=0.5)
            y_norm = _float_safe(planned_character.get("y_norm"), default=0.72)
            scale = max(0.2, _float_safe(planned_character.get("scale"), default=1.0) * max(0.2, camera_zoom))
            if showcase_mode:
                x_norm = 0.5
                y_norm = 0.92
                scale = max(0.9, scale * 1.48)
            state = _clean(planned_character.get("state")).lower() or "idle"
            emotion = _clean(planned_character.get("emotion")).lower() or "neutral"
            pose = _clean(planned_character.get("pose")).lower() or "idle"
            viseme = _clean(planned_character.get("viseme")).upper() or "X"
            is_active = bool(planned_character.get("is_active", False))
            t_ms = _int_safe(planned_character.get("t_ms"), default=0)
            secondary_motion_raw = planned_character.get("secondary_motion", {})
            secondary_motion = secondary_motion_raw if isinstance(secondary_motion_raw, dict) else {}
            anchor_map = character.get("anchor", {}) if isinstance(character, dict) and isinstance(character.get("anchor"), dict) else {}
            anchor_x = _float_safe(anchor_map.get("x"), default=0.5)
            anchor_y = _float_safe(anchor_map.get("y"), default=1.0)

            if showcase_mode:
                center_x = int(width * x_norm)
                center_y = int(height * y_norm)
            else:
                center_x = int((width * x_norm) + (camera_shift_x * 0.95))
                center_y = int((height * y_norm) + (camera_shift_y * 0.95))
            sprite_drawn = False

            use_cache_sprite = avatar_mode == "cache_sprite" or not showcase_mode
            if (
                use_cache_sprite
                and flat_asset_sprite_service is not None
                and isinstance(character, dict)
                and _clean(character.get("asset_mode")).lower() == "flat_assets_direct"
            ):
                try:
                    target_h = max(48, int(height * (0.62 if showcase_mode else 0.3) * scale))
                    target_w = max(36, int(target_h * (0.44 if showcase_mode else 0.36)))
                    sprite = flat_asset_sprite_service.render_sprite(
                        character=character,
                        state=("talk" if state == "talk" else "blink" if state == "blink" else "idle"),
                        emotion=emotion,
                        viseme=viseme,
                        pose=pose,
                        t_ms=t_ms,
                        target_size=(target_w, target_h),
                    )
                    if sprite is not None:
                        motion = _sprite_motion_offsets(
                            t_ms=t_ms,
                            char_id=char_id,
                            state=state,
                            is_active=is_active,
                            showcase_mode=showcase_mode,
                            secondary_motion=secondary_motion,
                        )
                        target_w = max(24, int(round(target_w * motion["scale_x"])))
                        target_h = max(24, int(round(target_h * motion["scale_y"])))
                        sprite = sprite.resize((target_w, target_h))
                        rotate_deg = motion["rotation_deg"]
                        if abs(rotate_deg) >= 0.05:
                            sprite = sprite.rotate(
                                rotate_deg,
                                resample=getattr(image_module, "BICUBIC", 3),
                                expand=True,
                            )
                        sprite_w, sprite_h = sprite.size
                        left = int(center_x - (sprite_w * anchor_x) + motion["x_px"])
                        top = int(center_y - (sprite_h * anchor_y) + motion["y_px"])
                        image.paste(sprite, (left, top), sprite)
                        sprite_drawn = True
                        if is_active and not showcase_mode:
                            drawer.rounded_rectangle(
                                (left - 6, top - 6, left + sprite_w + 6, top + sprite_h + 6),
                                radius=12,
                                outline=(236, 244, 255),
                                width=3,
                            )
                        if not showcase_mode:
                            bbox = drawer.textbbox((0, 0), name, font=name_font)
                            text_w = max(0, bbox[2] - bbox[0])
                            drawer.text((center_x - text_w // 2, top + sprite_h + 8), name, fill=(242, 246, 255), font=name_font)
                except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                    sprite_drawn = False

            if (
                use_cache_sprite
                and
                not sprite_drawn
                and
                lottie_cache_service is not None
                and isinstance(character, dict)
                and _clean(character.get("asset_mode")).lower() == "lottie_cache"
            ):
                try:
                    frame_path = lottie_cache_service.resolve_frame_path(
                        character=character,
                        state=("talk" if state == "talk" else "blink" if state == "blink" else "idle"),
                        emotion=emotion,
                        viseme=viseme,
                        t_ms=t_ms,
                        cache_fps=max(
                            1,
                            _int_safe(
                                frame_plan.get("cache_fps"),
                                default=max(12, _int_safe(frame_plan.get("fps"), default=24)),
                            ),
                        ),
                    )
                    sprite = image_module.open(frame_path).convert("RGBA")
                    target_h = max(48, int(height * (0.62 if showcase_mode else 0.3) * scale))
                    ratio = max(0.1, float(sprite.size[0]) / float(max(sprite.size[1], 1)))
                    target_w = max(36, int(target_h * ratio))
                    motion = _sprite_motion_offsets(
                        t_ms=t_ms,
                        char_id=char_id,
                        state=state,
                        is_active=is_active,
                        showcase_mode=showcase_mode,
                        secondary_motion=secondary_motion,
                    )
                    target_w = max(24, int(round(target_w * motion["scale_x"])))
                    target_h = max(24, int(round(target_h * motion["scale_y"])))
                    sprite = sprite.resize((target_w, target_h))
                    rotate_deg = motion["rotation_deg"]
                    if abs(rotate_deg) >= 0.05:
                        sprite = sprite.rotate(
                            rotate_deg,
                            resample=getattr(image_module, "BICUBIC", 3),
                            expand=True,
                        )
                    sprite_w, sprite_h = sprite.size
                    left = int(center_x - (sprite_w * anchor_x) + motion["x_px"])
                    top = int(center_y - (sprite_h * anchor_y) + motion["y_px"])
                    image.paste(sprite, (left, top), sprite)
                    sprite_drawn = True
                    if is_active and not showcase_mode:
                        drawer.rounded_rectangle(
                            (left - 6, top - 6, left + sprite_w + 6, top + sprite_h + 6),
                            radius=12,
                            outline=(236, 244, 255),
                            width=3,
                        )
                    if not showcase_mode:
                        bbox = drawer.textbbox((0, 0), name, font=name_font)
                        text_w = max(0, bbox[2] - bbox[0])
                        drawer.text((center_x - text_w // 2, top + sprite_h + 8), name, fill=(242, 246, 255), font=name_font)
                except (AttributeError, OSError, RuntimeError, TypeError, ValueError, FileNotFoundError):
                    sprite_drawn = False

            if sprite_drawn:
                continue

            if showcase_mode and avatar_mode == "procedural_presenter":
                self._draw_showcase_procedural_presenter(
                    drawer=drawer,
                    width=width,
                    height=height,
                    center_x=center_x,
                    center_y=center_y,
                    scale=scale,
                    character=character,
                    state=state,
                    pose=pose,
                    viseme=viseme,
                    emotion=emotion,
                    t_ms=t_ms,
                    is_active=is_active,
                    secondary_motion=secondary_motion,
                )
                continue

            rgb = _hex_to_rgb(_clean(character.get("color_hex"))) or (95, 140, 210)
            rr = max(26, int(min(width, height) * (0.08 if not showcase_mode else 0.16) * scale))
            lift = int(rr * (0.12 if is_active else 0.04))
            outline = (245, 247, 255) if is_active and not showcase_mode else (186, 198, 218)
            outline_width = 6 if is_active and not showcase_mode else 3
            drawer.ellipse(
                (center_x - rr, center_y - rr - lift, center_x + rr, center_y + rr - lift),
                fill=rgb,
                outline=outline,
                width=outline_width,
            )
            eye_y = center_y - int(rr * 0.2) - lift
            eye_dx = int(rr * 0.28)
            eye_r = max(2, int(rr * 0.07))
            if state == "blink":
                drawer.line(
                    (center_x - eye_dx - eye_r, eye_y, center_x - eye_dx + eye_r, eye_y),
                    fill=(18, 24, 34),
                    width=2,
                )
                drawer.line(
                    (center_x + eye_dx - eye_r, eye_y, center_x + eye_dx + eye_r, eye_y),
                    fill=(18, 24, 34),
                    width=2,
                )
            else:
                drawer.ellipse(
                    (center_x - eye_dx - eye_r, eye_y - eye_r, center_x - eye_dx + eye_r, eye_y + eye_r),
                    fill=(18, 24, 34),
                )
                drawer.ellipse(
                    (center_x + eye_dx - eye_r, eye_y - eye_r, center_x + eye_dx + eye_r, eye_y + eye_r),
                    fill=(18, 24, 34),
                )
            mouth_center_y = center_y + int(rr * 0.18) - lift
            mouth_w = int(rr * (0.55 if is_active else 0.34))
            if state == "talk":
                mouth_h = max(2, int(rr * _viseme_open_ratio(viseme)))
                drawer.ellipse(
                    (center_x - mouth_w // 2, mouth_center_y - mouth_h // 2, center_x + mouth_w // 2, mouth_center_y + mouth_h // 2),
                    fill=(15, 18, 28),
                )
            else:
                drawer.line(
                    (center_x - mouth_w // 2, mouth_center_y, center_x + mouth_w // 2, mouth_center_y),
                    fill=(20, 26, 38),
                    width=3,
                )
            if not showcase_mode:
                bbox = drawer.textbbox((0, 0), name, font=name_font)
                text_w = max(0, bbox[2] - bbox[0])
                drawer.text((center_x - text_w // 2, center_y + rr + 12 - lift), name, fill=(242, 246, 255), font=name_font)

    def _draw_showcase_procedural_presenter(
        self,
        *,
        drawer: Any,
        width: int,
        height: int,
        center_x: int,
        center_y: int,
        scale: float,
        character: CartoonCharacterSpec,
        state: str,
        pose: str,
        viseme: str,
        emotion: str,
        t_ms: int,
        is_active: bool,
        secondary_motion: dict[str, object] | None = None,
    ) -> None:
        _ = width
        base_rgb = _hex_to_rgb(_clean(character.get("color_hex"))) or (95, 140, 210)
        skin_rgb = _tint_color((236, 205, 172), tint=(10, -6, -4), amount=0.12 if _clean(emotion).lower() == "tense" else 0.0)
        shirt_rgb = _emotion_tinted(base_rgb, emotion=emotion)
        outline = (22, 28, 34)
        motion_map = secondary_motion if isinstance(secondary_motion, dict) else {}

        body_h = max(180, int(height * 0.64 * max(0.7, scale)))
        body_w = int(body_h * 0.42)
        foot_y = center_y
        torso_top = foot_y - int(body_h * 0.62)
        torso_bottom = foot_y - int(body_h * 0.16)
        torso_left = center_x - body_w // 2
        torso_right = center_x + body_w // 2

        phase = (max(0, int(t_ms)) % 1600) / 1600.0
        breath = math.sin(phase * math.pi * 2.0)
        sway_px = _float_safe(motion_map.get("torso_sway_px"), default=0.0)
        nod_deg = _float_safe(motion_map.get("head_nod_deg"), default=0.0)
        gesture_intensity = max(0.6, _float_safe(motion_map.get("gesture_intensity"), default=1.0))
        bob = int(round((3.0 * breath) + (sway_px * 0.35)))
        talk_state = _clean(state).lower() == "talk"
        pose_key = _clean(pose).lower() or ("open" if talk_state else "idle")

        # Legs
        leg_w = max(12, int(body_w * 0.28))
        leg_h = max(40, int(body_h * 0.2))
        leg_y0 = torso_bottom + bob
        drawer.rounded_rectangle(
            (center_x - leg_w - 4, leg_y0, center_x - 4, leg_y0 + leg_h),
            radius=6,
            fill=(52, 78, 112),
            outline=outline,
            width=2,
        )
        drawer.rounded_rectangle(
            (center_x + 4, leg_y0, center_x + leg_w + 4, leg_y0 + leg_h),
            radius=6,
            fill=(52, 78, 112),
            outline=outline,
            width=2,
        )

        # Torso
        drawer.rounded_rectangle(
            (torso_left, torso_top + bob, torso_right, torso_bottom + bob),
            radius=max(16, int(body_w * 0.15)),
            fill=shirt_rgb,
            outline=outline,
            width=3,
        )

        # Arms with pose choreography
        shoulder_y = torso_top + int((torso_bottom - torso_top) * 0.2) + bob
        arm_len = int(body_h * 0.22 * gesture_intensity)
        left_x, left_y, right_x, right_y = _presenter_arm_targets(
            pose=pose_key,
            arm_len=arm_len,
            talk_state=talk_state,
            t_ms=t_ms,
            is_active=is_active,
        )
        drawer.line(
            (torso_left + 6, shoulder_y, torso_left + left_x, shoulder_y + left_y),
            fill=shirt_rgb,
            width=max(9, int(body_w * 0.13)),
        )
        drawer.line(
            (torso_right - 6, shoulder_y, torso_right + right_x, shoulder_y + right_y),
            fill=shirt_rgb,
            width=max(9, int(body_w * 0.13)),
        )

        # Head
        head_r = max(40, int(body_h * 0.16))
        head_cx = center_x + int(round(sway_px * 0.6))
        head_cy = torso_top - head_r + int(bob * 0.8)
        drawer.ellipse(
            (head_cx - head_r, head_cy - head_r, head_cx + head_r, head_cy + head_r),
            fill=skin_rgb,
            outline=outline,
            width=3,
        )
        # Hair
        hair_h = int(head_r * 0.55)
        drawer.pieslice(
            (head_cx - head_r, head_cy - head_r - int(head_r * 0.25), head_cx + head_r, head_cy + hair_h),
            start=185,
            end=355,
            fill=(20, 24, 30),
            outline=(20, 24, 30),
        )

        # Eyes / blink
        eye_y = head_cy - int(head_r * 0.1)
        eye_dx = int(head_r * 0.36)
        eye_r = max(3, int(head_r * 0.08))
        blinking = _clean(state).lower() == "blink"
        if blinking:
            drawer.line((head_cx - eye_dx - eye_r, eye_y, head_cx - eye_dx + eye_r, eye_y), fill=(24, 28, 34), width=3)
            drawer.line((head_cx + eye_dx - eye_r, eye_y, head_cx + eye_dx + eye_r, eye_y), fill=(24, 28, 34), width=3)
        else:
            drawer.ellipse((head_cx - eye_dx - eye_r, eye_y - eye_r, head_cx - eye_dx + eye_r, eye_y + eye_r), fill=(24, 28, 34))
            drawer.ellipse((head_cx + eye_dx - eye_r, eye_y - eye_r, head_cx + eye_dx + eye_r, eye_y + eye_r), fill=(24, 28, 34))

        # Mouth
        mouth_y = head_cy + int(head_r * 0.38)
        mouth_w = int(head_r * 0.62)
        if talk_state:
            mouth_h = max(4, int(head_r * _viseme_open_ratio(viseme) * (1.35 if is_active else 1.15)))
            drawer.ellipse(
                (head_cx - mouth_w // 2, mouth_y - mouth_h // 2, head_cx + mouth_w // 2, mouth_y + mouth_h // 2),
                fill=(50, 17, 24),
                outline=(25, 28, 35),
                width=2,
            )
        else:
            smile = 2 if _clean(emotion).lower() in {"warm", "inspiring"} else 0
            drawer.arc(
                (head_cx - mouth_w // 2, mouth_y - 6, head_cx + mouth_w // 2, mouth_y + 10 + smile),
                start=12,
                end=168,
                fill=(25, 28, 35),
                width=3,
            )
        if abs(nod_deg) > 0.1:
            chin_y = head_cy + int(head_r * 0.54)
            chin_shift = int(round(nod_deg))
            drawer.line(
                (head_cx - int(head_r * 0.2), chin_y, head_cx + int(head_r * 0.2), chin_y + chin_shift),
                fill=(22, 26, 32),
                width=2,
            )

    def _draw_subtitle(
        self,
        *,
        drawer: Any,
        width: int,
        height: int,
        font_module: Any,
        active_turn: CartoonDialogueTurn | None,
        character_roster: list[CartoonCharacterSpec],
        progress: float,
    ) -> None:
        if active_turn is None:
            return
        text = _clean(active_turn.get("text"))
        if not text:
            return
        speaker_name = _clean(active_turn.get("speaker_name")) or "Speaker"
        speaker_id = _clean(active_turn.get("speaker_id"))
        subtitle = self._subtitle_service.compose_line(
            speaker_name=speaker_name,
            text=text,
            max_chars=88,
            max_lines=2,
        )
        if not subtitle:
            return
        lines = subtitle.splitlines() or [subtitle]
        subtitle_font = _font(font_module=font_module, size=max(23, int(min(width, height) * 0.024)), bold=True)
        block_height = int(height * (0.11 + (0.038 * (len(lines) - 1))))
        top = height - block_height - 18
        subtitle_color = self._subtitle_service.speaker_color(speaker_id, character_roster)

        pop = 1.0 + (0.02 * _sin_like(progress, period=0.23))
        left = int(36 - ((pop - 1.0) * 40.0))
        right = int(width - 36 + ((pop - 1.0) * 40.0))
        drawer.rounded_rectangle(
            (left, top, right, height - 18),
            radius=16,
            fill=(8, 12, 20),
            outline=(subtitle_color[0], subtitle_color[1], subtitle_color[2]),
            width=3,
        )

        line_height = max(18, int(subtitle_font.size * 1.2)) if subtitle_font is not None else 26
        text_total_h = line_height * len(lines)
        baseline_y = top + max(8, (block_height - text_total_h) // 2)
        for idx, line in enumerate(lines):
            bbox = drawer.textbbox((0, 0), line, font=subtitle_font)
            text_w = max(0, bbox[2] - bbox[0])
            x = max(left + 22, (width - text_w) // 2)
            y = baseline_y + (idx * line_height)
            drawer.text((x, y), line, fill=(240, 246, 255), font=subtitle_font)

    @staticmethod
    def _apply_grade(*, image_module: Any, image: Any, mood: str) -> Any:
        mood_key = _clean(mood).lower()
        tint = {
            "neutral": (14, 16, 24),
            "energetic": (26, 18, 34),
            "tense": (24, 16, 16),
            "warm": (28, 20, 10),
            "inspiring": (10, 20, 32),
        }.get(mood_key, (14, 16, 24))
        try:
            overlay = image_module.new("RGB", image.size, tint)
            return image_module.blend(image, overlay, 0.08)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            return image

    @staticmethod
    def _apply_transition_overlay(
        *,
        image_module: Any,
        image: Any,
        transition_in: str,
        transition_out: str,
        progress: float,
    ) -> Any:
        in_key = _clean(transition_in).lower()
        out_key = _clean(transition_out).lower()
        alpha = 0.0
        if in_key in {"crossfade", "fade_black"} and progress < 0.12:
            alpha = max(alpha, (0.12 - progress) / 0.12 * (0.7 if in_key == "fade_black" else 0.45))
        if out_key in {"crossfade", "fade_black"} and progress > 0.88:
            alpha = max(alpha, (progress - 0.88) / 0.12 * (0.7 if out_key == "fade_black" else 0.45))
        if alpha <= 0.0:
            return image
        try:
            overlay = image_module.new("RGB", image.size, (0, 0, 0))
            return image_module.blend(image, overlay, min(alpha, 0.8))
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            return image


def _font(*, font_module: Any, size: int, bold: bool) -> Any:
    candidates = [
        "C:\\Windows\\Fonts\\arialbd.ttf" if bold else "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\segoeuib.ttf" if bold else "C:\\Windows\\Fonts\\segoeui.ttf",
    ]
    for path in candidates:
        try:
            return font_module.truetype(path, size)
        except (AttributeError, OSError, ValueError):
            continue
    try:
        return font_module.load_default()
    except (AttributeError, OSError, ValueError):
        return None


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int] | None:
    cleaned = hex_color.strip().lstrip("#")
    if len(cleaned) != 6:
        return None
    try:
        return tuple(int(cleaned[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def _camera_transform(*, camera_move: str, progress: float) -> tuple[float, float, float]:
    move = _clean(camera_move).lower()
    if move == "push_in":
        return 0.0, -2.0, 1.0 + (0.08 * progress)
    if move == "pull_out":
        return 0.0, 1.0, 1.08 - (0.08 * progress)
    if move == "pan_left":
        return -24.0 * progress, 0.0, 1.0
    if move == "pan_right":
        return 24.0 * progress, 0.0, 1.0
    return 0.0, 0.0, 1.0


def _find_character_index(roster: list[CartoonCharacterSpec], character_id: str) -> int:
    target = _clean(character_id).lower()
    if not target:
        return -1
    for idx, item in enumerate(roster):
        if _clean(item.get("id")).lower() == target:
            return idx
    return -1


def _resolve_render_style(value: object) -> str:
    if _clean(value).lower() == "character_showcase":
        return "character_showcase"
    return "scene"


def _resolve_background_style(background_style: object, *, render_style: str) -> str:
    raw = _clean(background_style).lower()
    if raw == "auto":
        return "chroma_green" if _resolve_render_style(render_style) == "character_showcase" else "scene"
    if raw in {"scene", "chroma_green"}:
        return raw
    return "scene"


def _resolve_showcase_avatar_mode(mode: object, *, showcase_mode: bool) -> str:
    raw = _clean(mode).lower()
    if not showcase_mode:
        return "cache_sprite"
    if raw in {"cache_sprite", "procedural_presenter"}:
        return raw
    return "cache_sprite"


def _showcase_subject(planned: list[dict[str, object]]) -> dict[str, object]:
    for item in planned:
        if bool(item.get("is_active", False)):
            return item
    return planned[0] if planned else {}


def _showcase_subtitle_enabled(*, frame_plan: dict[str, object] | None) -> bool:
    if not isinstance(frame_plan, dict):
        return False
    track = frame_plan.get("subtitle_track", {})
    if not isinstance(track, dict):
        return False
    style = _clean(track.get("style")).lower()
    return style in {"showcase_box", "showcase_subtitle", "forced", "always"}


def _sprite_motion_offsets(
    *,
    t_ms: int,
    char_id: str,
    state: str,
    is_active: bool,
    showcase_mode: bool,
    secondary_motion: dict[str, object] | None = None,
) -> dict[str, float]:
    motion_map = secondary_motion if isinstance(secondary_motion, dict) else {}
    seed = sum(ord(ch) for ch in _clean(char_id)) % 997
    now = max(0, int(t_ms))
    base = (now + (seed * 17)) / 1000.0
    pulse = math.sin(base * (2.0 * math.pi))
    slow = math.sin(base * (2.0 * math.pi) * 0.45)
    torso_sway_px = _float_safe(motion_map.get("torso_sway_px"), default=0.0)
    head_nod_deg = _float_safe(motion_map.get("head_nod_deg"), default=0.0)
    gesture_intensity = _float_safe(motion_map.get("gesture_intensity"), default=1.0)
    scale_x = 1.0
    scale_y = 1.0
    x_px = 0.0
    y_px = -2.0 * slow
    rotation_deg = 0.0

    state_key = _clean(state).lower()
    if state_key == "talk":
        mouth_cycle = abs(math.sin(base * (2.0 * math.pi) * 2.4))
        scale_x *= 1.0 + (0.03 * mouth_cycle)
        scale_y *= 1.0 - (0.045 * mouth_cycle)
        y_px += 1.8 * pulse
        rotation_deg += 0.8 * pulse
    elif state_key == "blink":
        scale_y *= 0.96
        y_px += 1.5
    else:
        # Idle "breathing" to avoid frozen look when cache variants have low frame count.
        scale_x *= 1.0 - (0.012 * slow)
        scale_y *= 1.0 + (0.02 * slow)

    x_px += torso_sway_px * 0.32
    rotation_deg += head_nod_deg * 0.45
    scale_x *= 1.0 + ((gesture_intensity - 1.0) * 0.04)
    scale_y *= 1.0 - ((gesture_intensity - 1.0) * 0.035)

    if is_active:
        rotation_deg += 0.7 * slow
        y_px += 1.0 * pulse
    if showcase_mode:
        scale_x *= 1.02
        scale_y *= 1.02
        y_px += 2.5 * pulse
        rotation_deg += 0.5 * slow

    return {
        "scale_x": max(0.84, min(scale_x, 1.18)),
        "scale_y": max(0.84, min(scale_y, 1.18)),
        "x_px": max(-6.0, min(x_px, 6.0)),
        "y_px": max(-10.0, min(y_px, 10.0)),
        "rotation_deg": max(-3.0, min(rotation_deg, 3.0)),
    }


def _emotion_tinted(base_rgb: tuple[int, int, int], *, emotion: str) -> tuple[int, int, int]:
    mood = _clean(emotion).lower()
    if mood == "energetic":
        return _tint_color(base_rgb, tint=(26, 18, 10), amount=0.22)
    if mood == "tense":
        return _tint_color(base_rgb, tint=(18, -12, -8), amount=0.2)
    if mood == "warm":
        return _tint_color(base_rgb, tint=(24, 10, -10), amount=0.2)
    if mood == "inspiring":
        return _tint_color(base_rgb, tint=(-8, 8, 20), amount=0.22)
    return _tint_color(base_rgb, tint=(0, 0, 0), amount=0.0)


def _tint_color(rgb: tuple[int, int, int], *, tint: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    alpha = max(0.0, min(float(amount), 1.0))
    return (
        _clip_channel(rgb[0] + (tint[0] * alpha)),
        _clip_channel(rgb[1] + (tint[1] * alpha)),
        _clip_channel(rgb[2] + (tint[2] * alpha)),
    )


def _presenter_arm_targets(
    *,
    pose: str,
    arm_len: int,
    talk_state: bool,
    t_ms: int,
    is_active: bool,
) -> tuple[int, int, int, int]:
    beat = math.sin((max(0, int(t_ms)) % 900) / 900.0 * math.pi * 2.0)
    idle_drop = int(arm_len * (0.92 - (0.04 if is_active else 0.0)))
    left = (-int(arm_len * 0.35), idle_drop)
    right = (int(arm_len * 0.35), idle_drop)
    pose_key = _clean(pose).lower()

    if pose_key == "point_right":
        right = (int(arm_len * 1.0), -int(arm_len * 0.52))
    elif pose_key == "point_left":
        left = (-int(arm_len * 1.0), -int(arm_len * 0.52))
    elif pose_key == "open":
        left = (-int(arm_len * 0.78), -int(arm_len * 0.22))
        right = (int(arm_len * 0.78), -int(arm_len * 0.22))
    elif pose_key in {"emphasis", "raise_both"}:
        left = (-int(arm_len * 0.62), -int(arm_len * 0.58))
        right = (int(arm_len * 0.62), -int(arm_len * 0.58))
    elif pose_key == "hand_over_heart":
        left = (-int(arm_len * 0.34), idle_drop)
        right = (int(arm_len * 0.05), int(arm_len * 0.18))
    elif talk_state:
        right = (int(arm_len * 0.9), -int(arm_len * 0.42))

    if talk_state:
        right = (right[0], right[1] - int(arm_len * 0.08 * beat))
    return left[0], left[1], right[0], right[1]


def _clip_channel(value: float) -> int:
    return int(max(0, min(255, round(float(value)))))


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _int_safe(value: object, *, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _float_safe(value: object, *, default: float) -> float:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return float(value)
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _sin_like(progress: float, *, period: float) -> float:
    safe_period = max(period, 0.05)
    normalized = (progress / safe_period) % 1.0
    if normalized <= 0.5:
        return (normalized * 2.0) - 0.5
    return 0.5 - ((normalized - 0.5) * 2.0)


def _viseme_open_ratio(viseme: str) -> float:
    mapping = {
        "A": 0.18,
        "B": 0.12,
        "C": 0.14,
        "D": 0.1,
        "E": 0.16,
        "F": 0.08,
        "G": 0.15,
        "H": 0.11,
        "X": 0.04,
    }
    return mapping.get(_clean(viseme).upper(), 0.1)
