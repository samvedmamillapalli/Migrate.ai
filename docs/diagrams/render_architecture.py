"""Devpost architecture: how CockroachDB, AWS, and the agent interact."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 2400, 1540
OUT = Path(__file__).with_name("architecture-agent-aws-crdb.png")

BG = (248, 247, 244)
CARD = (255, 255, 255)
SURFACE = (243, 241, 236)
SHADOW = (232, 228, 220)
INK = (53, 47, 43)
MUTED = (122, 114, 104)
BORDER = (230, 226, 218)
PRIMARY = (129, 29, 29)
TINT = (252, 246, 244)


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


def card(draw, box, fill=CARD, outline=BORDER, width=2, shadow=True):
    x0, y0, x1, y1 = box
    if shadow:
        draw.rounded_rectangle(
            (x0 + 5, y0 + 7, x1 + 5, y1 + 7), radius=14, fill=SHADOW
        )
    round_rect(draw, box, fill, outline, 14, width)


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


def h_arrow(draw, x0, y, x1):
    draw.line((x0, y, x1 - 16, y), fill=PRIMARY, width=4)
    draw.polygon([(x1, y), (x1 - 16, y - 8), (x1 - 16, y + 8)], fill=PRIMARY)


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text(
        (64, 36),
        no_dash("HOW COCKROACHDB, AWS, AND THE AGENT INTERACT"),
        font=sans(22, True),
        fill=PRIMARY,
    )
    d.text((64, 72), no_dash("Migration Oracle"), font=display(64), fill=INK)
    d.text(
        (64, 152),
        no_dash(
            "The agent reads memory in CockroachDB, calls Bedrock, then verifies on a disposable Cloud cluster."
        ),
        font=sans(26),
        fill=MUTED,
    )

    left = 56
    gutter = 36
    usable = W - 112
    col_w = (usable - 2 * gutter) // 3
    top = 214
    col_h = 780
    pad = 32

    cols = [
        (
            "THE AGENT",
            "FastAPI",
            True,
            [
                "Next.js console  ·  Clerk",
                "GitHub PR webhook  ·  optional Slack DMs",
                "",
                "1.  Discover schema (read only)",
                "2.  Policy check (can block)",
                "3.  Retrieve similar memories",
                "4.  Predict with Bedrock Claude",
                "      duration, storage, rollback, confidence",
                "5.  Human clicks proceed",
                "6.  Start Step Functions",
                "      (run id and secret ARN only)",
            ],
        ),
        (
            "COCKROACHDB",
            "Memory and the cluster under test",
            False,
            [
                "App database",
                "      runs, predictions, approvals, grades",
                "",
                "Distributed Vector Index",
                "      Titan v2 embeddings as VECTOR(1024)",
                "      cosine, owner prefix, ready rows only",
                "      retrieval feeds the next predict",
                "",
                "Disposable Cloud cluster",
                "      BASIC, via the Cloud REST API",
                "      schema loaded, SQL executed",
                "      live progress via SHOW JOB by id",
                "",
                "Managed MCP Server (hosted)",
                "      Lambda is the client, not the server",
            ],
        ),
        (
            "AWS",
            "Models, workflow, and secrets",
            False,
            [
                "Bedrock  ·  Claude + Titan v2",
                "Step Functions  ·  7 Lambda steps",
                "      Cleanup always runs, including on failure",
                "Lambda  ·  8 functions",
                "      discover, provision, load, execute,",
                "      collect, persist and grade, cleanup,",
                "      and a 15 min EventBridge sweeper",
                "",
                "S3  ·  snapshots and reports",
                "Secrets Manager  ·  DB credentials",
                "CloudWatch  ·  metrics and logs",
                "Lightsail  ·  hosts the live app",
                "",
                "Cleanup holds about 5 min, then the",
                "sweeper deletes the cluster.",
            ],
        ),
    ]

    boxes = []
    body_f = sans(26)
    for i, (kicker, title, accent, body) in enumerate(cols):
        x0 = left + i * (col_w + gutter)
        x1 = x0 + col_w
        y0, y1 = top, top + col_h
        boxes.append((x0, y0, x1, y1))
        card(d, (x0, y0, x1, y1), CARD, PRIMARY, 3 if accent else 2)
        if accent:
            d.rectangle((x0, y0, x0 + 10, y1), fill=PRIMARY)
        inset = pad + (6 if accent else 0)
        d.text((x0 + inset, y0 + 24), no_dash(kicker), font=sans(18, True), fill=PRIMARY)
        d.text((x0 + inset, y0 + 54), no_dash(title), font=sans(28, True), fill=INK)
        d.line((x0 + inset, y0 + 100, x1 - pad, y0 + 100), fill=BORDER, width=2)
        y = y0 + 118
        max_w = col_w - inset - pad
        for item in body:
            if item == "":
                y += 14
                continue
            for line in wrap(d, item, body_f, max_w):
                d.text((x0 + inset, y), line, font=body_f, fill=INK)
                y += 38

    # Visual rhythm between the three parties (the row below is the real wiring)
    cy = top + 48
    for i in range(2):
        h_arrow(d, boxes[i][2] + 2, cy, boxes[i + 1][0] - 2)

    # Visual interaction row
    strip_top = top + col_h + 28
    d.text(
        (left, strip_top),
        no_dash("HOW THEY CONNECT"),
        font=sans(18, True),
        fill=PRIMARY,
    )
    d.text(
        (left, strip_top + 28),
        no_dash("What talks to what"),
        font=sans(32, True),
        fill=INK,
    )

    flow_top = strip_top + 74
    flow_h = 360
    flow_gap = 28
    arrow_w = 36
    n = 4
    flow_w = (usable - 3 * (flow_gap + arrow_w)) // n
    flow = [
        (
            "1",
            "Predict",
            "Agent  ·  CockroachDB  ·  Bedrock",
            "Agent reads CockroachDB vector memory (CREATE VECTOR INDEX, cosine), then Bedrock Claude predicts duration, storage, rollback, and confidence.",
        ),
        (
            "2",
            "Verify",
            "Agent  ·  Step Functions  ·  Cloud",
            "After approval the agent starts Step Functions. Lambdas provision a BASIC cluster via the CockroachDB Cloud REST API, not the ccloud CLI.",
        ),
        (
            "3",
            "Inspect",
            "Execute Lambda  ·  shadow SQL  ·  MCP",
            "Execute Lambda runs the SQL, watches SHOW JOB by id, then the MCP client (read only) inspects blast radius on the hosted Managed MCP Server.",
        ),
        (
            "4",
            "Remember",
            "Persist  ·  Titan  ·  CockroachDB",
            "Persist grades predicted vs actual. The score is math, not the model. Titan embeds the lesson back into CockroachDB for the next predict.",
        ),
    ]

    fy0 = flow_top
    fy1 = fy0 + flow_h
    for i, (num, title, who, detail) in enumerate(flow):
        x0 = left + i * (flow_w + flow_gap + arrow_w)
        x1 = x0 + flow_w
        card(d, (x0, fy0, x1, fy1), TINT if i % 2 == 0 else CARD, PRIMARY, 2)
        # number badge
        bx, by = x0 + 22, fy0 + 22
        d.ellipse((bx, by, bx + 36, by + 36), fill=PRIMARY)
        nw = d.textlength(num, font=sans(20, True))
        d.text((bx + 18 - nw / 2, by + 5), num, font=sans(20, True), fill=(255, 255, 255))
        d.text((x0 + 68, fy0 + 24), no_dash(title), font=sans(28, True), fill=INK)
        d.text((x0 + 22, fy0 + 72), no_dash(who), font=sans(18, True), fill=PRIMARY)
        y = fy0 + 108
        for line in wrap(d, detail, sans(23), flow_w - 44):
            d.text((x0 + 22, y), line, font=sans(23), fill=INK)
            y += 32
        if i < 3:
            ax0 = x1 + 4
            ax1 = x1 + arrow_w + flow_gap - 4
            h_arrow(d, ax0, (fy0 + fy1) // 2, ax1)

    img.save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT} {img.size}")


if __name__ == "__main__":
    main()
