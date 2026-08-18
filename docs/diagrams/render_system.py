"""Layered system architecture: presentation, control, execution, memory."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 2400, 1760
OUT = Path(__file__).with_name("architecture-system.png")

BG = (248, 247, 244)
CARD = (255, 255, 255)
SURFACE = (243, 241, 236)
SHADOW = (232, 228, 220)
INK = (53, 47, 43)
MUTED = (122, 114, 104)
BORDER = (230, 226, 218)
PRIMARY = (129, 29, 29)
TINT = (252, 246, 244)
WHITE = (255, 255, 255)


def sans(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = (
        ["segoeuib.ttf", "calibrib.ttf", "arialbd.ttf"]
        if bold
        else ["segoeui.ttf", "calibri.ttf", "arial.ttf"]
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def display(size: int) -> ImageFont.FreeTypeFont:
    for name in ("georgia.ttf", "times.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return sans(size, True)


def no_dash(text: str) -> str:
    for ch in ("-", "–", "—", "−"):
        if ch in text:
            raise ValueError(f"dash not allowed: {text!r}")
    return text


def round_rect(draw, box, fill, outline=BORDER, radius=14, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def card(draw, box, fill=CARD, outline=PRIMARY, width=2, shadow=True):
    x0, y0, x1, y1 = box
    if shadow:
        draw.rounded_rectangle((x0 + 4, y0 + 6, x1 + 4, y1 + 6), radius=14, fill=SHADOW)
    round_rect(draw, box, fill, outline, 14, width)
    return box


def wrap(draw, text: str, font, max_width: int) -> list[str]:
    words = no_dash(text).split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def text_in(draw, x, y, text, font, fill=INK):
    draw.text((x, y), no_dash(text), font=font, fill=fill)


def center_text(draw, cx, y, text, font, fill=INK):
    t = no_dash(text)
    tw = draw.textlength(t, font=font)
    draw.text((cx - tw / 2, y), t, font=font, fill=fill)


def arrow_right(draw, x0, y, x1):
    if x1 - x0 < 20:
        return
    draw.line((x0, y, x1 - 14, y), fill=PRIMARY, width=3)
    draw.polygon([(x1, y), (x1 - 14, y - 7), (x1 - 14, y + 7)], fill=PRIMARY)


def arrow_down(draw, x, y0, y1):
    if y1 - y0 < 20:
        return
    draw.line((x, y0, x, y1 - 14), fill=PRIMARY, width=3)
    draw.polygon([(x, y1), (x - 7, y1 - 14), (x + 7, y1 - 14)], fill=PRIMARY)


def arrow_up(draw, x, y_bottom, y_top):
    if y_bottom - y_top < 20:
        return
    draw.line((x, y_bottom, x, y_top + 14), fill=PRIMARY, width=3)
    draw.polygon([(x, y_top), (x - 7, y_top + 14), (x + 7, y_top + 14)], fill=PRIMARY)


def label_pill(draw, x, y, text, font):
    t = no_dash(text)
    tw = draw.textlength(t, font=font)
    box = (x, y, x + tw + 20, y + font.size + 10)
    round_rect(draw, box, WHITE, PRIMARY, 10, 1)
    draw.text((x + 10, y + 4), t, font=font, fill=PRIMARY)
    return box


def node(draw, box, title, lines, *, fill=CARD, title_size=22, body_size=18, accent=False):
    card(draw, box, TINT if accent else fill, PRIMARY, 3 if accent else 2)
    x0, y0, x1, _y1 = box
    text_in(draw, x0 + 18, y0 + 14, title, sans(title_size, True), INK)
    y = y0 + 50
    body = sans(body_size)
    max_w = x1 - x0 - 36
    for line in lines:
        if not line:
            y += 6
            continue
        for wrapped in wrap(draw, line, body, max_w):
            text_in(draw, x0 + 18, y, wrapped, body, INK)
            y += body_size + 7
    return box


def lane(draw, y0, y1, num, title):
    round_rect(draw, (40, y0, W - 40, y1), SURFACE, BORDER, 18, 1)
    draw.rectangle((40, y0, 52, y1), fill=PRIMARY)
    cx = 130
    draw.ellipse((cx - 30, y0 + 22, cx + 30, y0 + 82), fill=PRIMARY)
    center_text(draw, cx, y0 + 34, num, sans(28, True), WHITE)
    font = sans(17, True)
    y = y0 + 96
    for line in wrap(draw, title, font, 160):
        tw = draw.textlength(line, font=font)
        draw.text((cx - tw / 2, y), line, font=font, fill=PRIMARY)
        y += 22


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    text_in(d, 56, 24, "MIGRATION ORACLE ARCHITECTURE", sans(18, True), PRIMARY)
    text_in(d, 56, 56, "Migration Oracle", display(54), INK)
    text_in(
        d,
        56,
        122,
        "Predict, verify on a disposable Cloud cluster, grade, then remember in CockroachDB.",
        sans(24),
        MUTED,
    )

    L = 250
    R = W - 56
    gap = 28

    # Column guides: left / mid / right
    left_r = 980
    mid_l, mid_r = 1010, 1660
    right_l = 1690

    # ---- 1 Presentation ----
    y0, y1 = 176, 390
    lane(d, y0, y1, "1", "Presentation")
    node(
        d,
        (L, y0 + 30, left_r, y1 - 24),
        "Next.js dashboard",
        ["Runs, predictions, approvals, memory browser.", "Hosted on Lightsail with FastAPI."],
        title_size=24,
        body_size=20,
    )
    node(
        d,
        (mid_l, y0 + 30, mid_r, y1 - 24),
        "Clerk auth",
        ["Session identity on every console request."],
        title_size=24,
        body_size=20,
    )
    node(
        d,
        (right_l, y0 + 30, R, y1 - 24),
        "GitHub PR webhook",
        ["Creates a run, discovers, predicts, then waits for a human to proceed."],
        title_size=22,
        body_size=19,
    )
    arrow_right(d, left_r, (y0 + y1) // 2 - 10, mid_l)
    label_pill(d, left_r + 8, (y0 + y1) // 2 - 36, "auth", sans(14, True))

    # ---- 2 Control plane ----
    y0, y1 = 414, 900
    lane(d, y0, y1, "2", "Control plane")
    fastapi = node(
        d,
        (L, y0 + 28, left_r, y1 - 28),
        "FastAPI on Lightsail",
        [
            "Schema discovery (read only on the customer DB)",
            "Policy engine (can block)",
            "Memory retrieval from the vector index",
            "Bedrock Claude prediction",
            "Human approval gate",
            "Starts Step Functions (run id and secret ARN only)",
            "Optional Slack DMs (from FastAPI, not Bedrock)",
        ],
        title_size=24,
        body_size=20,
        accent=True,
    )
    crdb = node(
        d,
        (mid_l, y0 + 28, mid_r, y1 - 28),
        "CockroachDB app database",
        [
            "Runs, predictions, approvals, grades",
            "VECTOR(1024) memories",
            "CREATE VECTOR INDEX, cosine",
            "Owner prefix, ready rows only",
            "Retrieval feeds the next predict, not the grade",
        ],
        fill=TINT,
        title_size=22,
        body_size=20,
        accent=True,
    )
    node(
        d,
        (right_l, y0 + 28, R, y1 - 28),
        "Amazon Bedrock",
        [
            "Claude: predict (FastAPI)",
            "Claude: MCP blast radius (Execute Lambda)",
            "Claude: lesson prose (Persist Lambda)",
            "Titan v2: embeddings (Persist Lambda)",
        ],
        title_size=22,
        body_size=19,
    )
    arrow_down(d, 520, 390, fastapi[1])
    label_pill(d, 536, 392, "HTTPS", sans(14, True))
    # GitHub hits FastAPI, not Bedrock
    gx, gy = right_l + 24, 366
    d.line((gx, gy, gx, 402), fill=PRIMARY, width=3)
    d.line((gx, 402, 700, 402), fill=PRIMARY, width=3)
    arrow_down(d, 700, 402, fastapi[1])
    label_pill(d, 980, 378, "webhook", sans(14, True))
    arrow_right(d, left_r, y0 + 160, mid_l)
    label_pill(d, left_r + 6, y0 + 124, "read / write", sans(14, True))
    arrow_right(d, mid_r, y0 + 160, right_l)
    label_pill(d, mid_r + 8, y0 + 124, "predict", sans(14, True))

    # ---- 3 Execution ----
    y0, y1 = 924, 1328
    lane(d, y0, y1, "3", "Execution plane")
    sfn = node(
        d,
        (L, y0 + 24, 720, y1 - 24),
        "AWS Step Functions",
        [
            "7 Lambda steps",
            "Cleanup always runs",
            "8th Lambda: 15 min EventBridge sweeper",
        ],
        title_size=22,
        body_size=19,
    )
    node(
        d,
        (752, y0 + 24, 1320, y1 - 24),
        "Lambda tasks",
        [
            "discover, provision, load",
            "execute, collect",
            "persist and grade, cleanup",
            "S3 artifacts · Secrets Manager",
        ],
        title_size=22,
        body_size=19,
    )
    node(
        d,
        (1352, y0 + 24, R, y0 + 210),
        "Disposable CockroachDB Cloud cluster",
        [
            "BASIC plan via the Cloud REST API, not the ccloud CLI",
            "Schema loaded, SQL executed, live progress via SHOW JOB by id",
        ],
        fill=TINT,
        title_size=20,
        body_size=18,
        accent=True,
    )
    node(
        d,
        (1352, y0 + 230, R, y1 - 24),
        "Execute Lambda",
        [
            "Runs the SQL and watches SHOW JOB by id",
            "MCP client (read only) talks to the hosted Managed MCP Server",
            "Cleanup holds about 5 min, then the sweeper deletes the cluster",
        ],
        title_size=20,
        body_size=17,
    )
    arrow_down(d, 500, 900, sfn[1])
    label_pill(d, 516, 902, "start SFN", sans(14, True))
    arrow_right(d, 720, y0 + 140, 752)
    arrow_right(d, 1320, y0 + 140, 1352)

    # ---- 4 Memory ----
    y0, y1 = 1352, 1716
    lane(d, y0, y1, "4", "Memory pipeline")
    grade = node(
        d,
        (L, y0 + 24, left_r, y1 - 24),
        "Grade",
        [
            "Predicted vs actual",
            "The score is math, not the model",
            "Claude writes lesson prose only",
            "Titan v2 embeds the lesson (1024 dimensions)",
        ],
        title_size=24,
        body_size=20,
    )
    node(
        d,
        (mid_l, y0 + 24, mid_r, y1 - 24),
        "Store graded memories",
        [
            "Written into CockroachDB VECTOR(1024)",
            "CREATE VECTOR INDEX, cosine, ready rows",
        ],
        fill=TINT,
        title_size=22,
        body_size=19,
        accent=True,
    )
    node(
        d,
        (right_l, y0 + 24, R, y1 - 24),
        "Closed loop",
        [
            "FastAPI retrieves similar memories before the next Bedrock predict.",
            "Retrieval does not feed the grade.",
        ],
        title_size=22,
        body_size=19,
    )
    arrow_down(d, 500, 1328, grade[1])
    label_pill(d, 516, 1330, "Persist Lambda", sans(14, True))
    arrow_right(d, left_r, (y0 + y1) // 2, mid_l)
    arrow_right(d, mid_r, (y0 + y1) // 2, right_l)

    img.save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT} {img.size}")


if __name__ == "__main__":
    main()
