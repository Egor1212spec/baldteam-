import os
import json
import socket
import struct
import threading
import random
import math
import pygame

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if load_dotenv is not None:
    load_dotenv(os.path.join(BASE_DIR, ".env"))

SERVER_IP = os.getenv("SERVER_IP", "127.0.0.1")
SERVER_PORT = int(os.getenv("SERVER_PORT", "5555"))
SERVER_PASSWORD = os.getenv("SERVER_PASSWORD", "my_super_password")
PLAYER_ROLE = os.getenv("PLAYER_ROLE", "rtp").lower()

CELL = 16
GRID_WIDTH = 960
PANEL_WIDTH = 300
WIDTH = GRID_WIDTH + PANEL_WIDTH
HEIGHT = 704
COLS = GRID_WIDTH // CELL
ROWS = HEIGHT // CELL
FPS = 30
TEXTURE_DIR = os.path.join(BASE_DIR, "textures")

available_trucks = []
firefighters_from_server = []
selected_truck_on_map = None
local_firefighters = []
active_ff_idx = -1
next_ff_id = 1

FF_SPEED = 0.15
STREAM_LEN = 6
SPRAY_LEN = 3
STREAM_CD = 3
SPRAY_CD = 2
WATER_PER_STREAM = 2
WATER_PER_SPRAY = 3
TRUCK_MAX_WATER = 2000
HOSE_MAX_LEN = 25
SUPPLY_HOSE_MAX = 15

truck_water_map = {}
supply_hoses = {}
supply_hose_mode = False
water_particles = []

DIR_VEC = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}


def make_font(size, bold=False):
    for p in ["C:/Windows/Fonts/arial.ttf",
              "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"]:
        if os.path.exists(p):
            try:
                return pygame.font.Font(p, size)
            except Exception:
                pass
    return pygame.font.SysFont("arial", size, bold=bold)


def recv_exact(s, n):
    buf = b""
    while len(buf) < n:
        ch = s.recv(n - len(buf))
        if not ch:
            return None
        buf += ch
    return buf


def send_to_server(data):
    try:
        raw = json.dumps(data).encode("utf-8")
        sock.sendall(struct.pack(">I", len(raw)) + raw)
    except Exception:
        pass


pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("FIRE SANDBOX - " + PLAYER_ROLE.upper())
clock = pygame.time.Clock()

font_main = make_font(18)
font_bold = make_font(20, True)
font_small = make_font(14)
font_tiny = make_font(12)

TEXTURES = {}
fire_texture = None
ff_base_texture = None
ff_dir_textures = {}


def load_all_textures():
    global TEXTURES, fire_texture, ff_base_texture, ff_dir_textures
    os.makedirs(TEXTURE_DIR, exist_ok=True)
    TEXTURES = {}

    try:
        fire_texture = pygame.image.load(
            os.path.join(BASE_DIR, "fire.png")).convert_alpha()
    except Exception:
        fire_texture = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
        fire_texture.fill((255, 100, 0, 180))

    ff_base_texture = None
    for name in ("fire_fighter.png", "firefighter.png"):
        fp = os.path.join(TEXTURE_DIR, name)
        if os.path.exists(fp):
            try:
                img = pygame.image.load(fp).convert_alpha()
                ff_base_texture = pygame.transform.scale(img, (CELL + 8, CELL + 8))
                break
            except Exception:
                pass
    if ff_base_texture is None:
        ff_base_texture = pygame.Surface((CELL + 8, CELL + 8), pygame.SRCALPHA)
        pygame.draw.circle(ff_base_texture, (0, 180, 255),
                           (CELL // 2 + 4, CELL // 2 + 4), 10)
        pygame.draw.rect(ff_base_texture, (200, 50, 50),
                         (CELL // 2 - 2, 0, 12, 6))

    ff_dir_textures["up"] = ff_base_texture
    ff_dir_textures["right"] = pygame.transform.rotate(ff_base_texture, -90)
    ff_dir_textures["down"] = pygame.transform.rotate(ff_base_texture, 180)
    ff_dir_textures["left"] = pygame.transform.rotate(ff_base_texture, 90)

    for d in ["up", "down", "left", "right"]:
        cp = ff_dir_textures[d].copy()
        ov = pygame.Surface(cp.get_size(), pygame.SRCALPHA)
        ov.fill((255, 255, 100, 60))
        cp.blit(ov, (0, 0))
        ff_dir_textures[d + "_act"] = cp

    for fn in os.listdir(TEXTURE_DIR):
        if not fn.lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        key = os.path.splitext(fn)[0].lower()
        if key in ("fire_fighter", "firefighter"):
            continue
        path = os.path.join(TEXTURE_DIR, fn)
        try:
            img = pygame.image.load(path).convert_alpha()
            if key == "firecar":
                TEXTURES["firecar"] = pygame.transform.scale(img, (64, 128))
            elif key in ("road", "road_straight"):
                TEXTURES["road"] = pygame.transform.scale(img, (CELL * 4, CELL * 4))
            elif key in ("road_right", "road_turn"):
                TEXTURES["road_right"] = pygame.transform.scale(
                    img, (CELL * 5, CELL * 5))
            else:
                TEXTURES[key] = pygame.transform.scale(img, (CELL, CELL))
        except Exception:
            pass


load_all_textures()

server_grid = [[[0, 0, "empty"] for _ in range(COLS)] for _ in range(ROWS)]
running_sim = False

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
connected = False
try:
    sock.connect((SERVER_IP, SERVER_PORT))
    auth = {"type": "AUTH", "password": SERVER_PASSWORD, "role": PLAYER_ROLE}
    raw = json.dumps(auth).encode("utf-8")
    sock.sendall(struct.pack(">I", len(raw)) + raw)
    connected = True
except Exception:
    pass


def recv_thread():
    global server_grid, running_sim, available_trucks
    global firefighters_from_server, supply_hoses
    while True:
        try:
            hdr = recv_exact(sock, 4)
            if not hdr:
                break
            mlen = struct.unpack(">I", hdr)[0]
            body = recv_exact(sock, mlen)
            if not body:
                break
            data = json.loads(body.decode("utf-8"))
            mt = data.get("type", "")
            if mt == "STATE_UPDATE":
                server_grid = data.get("grid", server_grid)
                running_sim = data.get("running_sim", False)
                available_trucks = data.get("available_trucks", [])
                firefighters_from_server = data.get("firefighters", [])
                sh_list = data.get("supply_hoses", [])
                supply_hoses.clear()
                for item in sh_list:
                    supply_hoses[(item[0], item[1])] = (item[2], item[3])
            elif mt == "TRUCK_AVAILABLE":
                available_trucks = data.get("available", [])
            elif mt == "SUPPLY_OK":
                tx = data.get("tx", 0)
                ty = data.get("ty", 0)
                sx = data.get("sx", 0)
                sy = data.get("sy", 0)
                supply_hoses[(tx, ty)] = (sx, sy)
        except Exception:
            break


if connected:
    threading.Thread(target=recv_thread, daemon=True).start()


def find_trucks_on_map():
    result = []
    for y in range(ROWS):
        for x in range(COLS):
            c = server_grid[y][x]
            ct = c[2] if len(c) > 2 else ""
            if "firecar" in ct and "_root" in ct:
                result.append((x, y))
    return result


def can_walk(gx, gy):
    if gx < 0 or gy < 0 or gx >= COLS or gy >= ROWS:
        return False
    return server_grid[int(gy)][int(gx)][1] <= 6


def is_truck_supplied(tx, ty):
    return (tx, ty) in supply_hoses


def get_tw(tx, ty):
    if is_truck_supplied(tx, ty):
        return TRUCK_MAX_WATER
    k = (tx, ty)
    if k not in truck_water_map:
        truck_water_map[k] = TRUCK_MAX_WATER
    return truck_water_map[k]


def use_tw(tx, ty, amt):
    if is_truck_supplied(tx, ty):
        return TRUCK_MAX_WATER
    k = (tx, ty)
    if k not in truck_water_map:
        truck_water_map[k] = TRUCK_MAX_WATER
    truck_water_map[k] = max(0, truck_water_map[k] - amt)
    return truck_water_map[k]


def hose_dist(ff):
    dx = ff["x"] - ff["tx"]
    dy = ff["y"] - ff["ty"]
    return math.sqrt(dx * dx + dy * dy)


def check_hose(ff, nx, ny):
    dx = nx - ff["tx"]
    dy = ny - ff["ty"]
    return math.sqrt(dx * dx + dy * dy) <= HOSE_MAX_LEN


def spawn_ff(tx, ty):
    global next_ff_id
    for dy in range(-2, 6):
        for dx in range(-2, 6):
            nx2 = tx + dx
            ny2 = ty + dy
            if 0 <= nx2 < COLS and 0 <= ny2 < ROWS:
                c = server_grid[ny2][nx2]
                ct = c[2] if len(c) > 2 else ""
                if c[1] < 3 and "firecar" not in ct:
                    ff = {
                        "id": next_ff_id,
                        "x": float(nx2),
                        "y": float(ny2),
                        "name": "Firefighter #" + str(next_ff_id),
                        "cd": 0,
                        "tx": tx,
                        "ty": ty,
                        "dir": "up",
                        "shooting": False,
                        "shoot_t": 0,
                        "mode": "stream",
                    }
                    next_ff_id += 1
                    return ff
    return None


def do_shoot_stream(ff):
    if ff["cd"] > 0:
        return
    tw = get_tw(ff["tx"], ff["ty"])
    if tw <= 0:
        return

    ff["cd"] = STREAM_CD
    ff["shooting"] = True
    ff["shoot_t"] = 8
    use_tw(ff["tx"], ff["ty"], WATER_PER_STREAM)

    ddx, ddy = DIR_VEC[ff["dir"]]
    cx = int(ff["x"])
    cy = int(ff["y"])
    cells = []
    for i in range(1, STREAM_LEN + 1):
        sx = cx + ddx * i
        sy = cy + ddy * i
        if sx < 0 or sx >= COLS or sy < 0 or sy >= ROWS:
            break
        cells.append({"x": sx, "y": sy})
        if ddx == 0:
            if sx - 1 >= 0:
                cells.append({"x": sx - 1, "y": sy})
            if sx + 1 < COLS:
                cells.append({"x": sx + 1, "y": sy})
        else:
            if sy - 1 >= 0:
                cells.append({"x": sx, "y": sy - 1})
            if sy + 1 < ROWS:
                cells.append({"x": sx, "y": sy + 1})

    if cells:
        send_to_server({"type": "EXTINGUISH", "cells": cells, "power": 5})

    px = ff["x"] * CELL + CELL // 2
    py = ff["y"] * CELL + CELL // 2
    for i in range(1, STREAM_LEN + 1):
        tgx = px + ddx * i * CELL
        tgy = py + ddy * i * CELL
        for _ in range(3):
            water_particles.append({
                "x": px + ddx * CELL * 0.5,
                "y": py + ddy * CELL * 0.5,
                "vx": ddx * i * 2.5 + random.uniform(-0.8, 0.8),
                "vy": ddy * i * 2.5 + random.uniform(-0.8, 0.8),
                "tgt_x": tgx + random.uniform(-4, 4),
                "tgt_y": tgy + random.uniform(-4, 4),
                "life": 6 + i * 2,
                "max_life": 6 + i * 2,
                "sz": random.randint(2, 4),
            })


def do_shoot_spray(ff):
    if ff["cd"] > 0:
        return
    tw = get_tw(ff["tx"], ff["ty"])
    if tw <= 0:
        return

    ff["cd"] = SPRAY_CD
    ff["shooting"] = True
    ff["shoot_t"] = 6
    use_tw(ff["tx"], ff["ty"], WATER_PER_SPRAY)

    ddx, ddy = DIR_VEC[ff["dir"]]
    cx = int(ff["x"])
    cy = int(ff["y"])
    cells = []
    for i in range(1, SPRAY_LEN + 1):
        spread = i + 1
        for s in range(-spread, spread + 1):
            if ddx == 0:
                sx = cx + s
                sy = cy + ddy * i
            else:
                sx = cx + ddx * i
                sy = cy + s
            if 0 <= sx < COLS and 0 <= sy < ROWS:
                cells.append({"x": sx, "y": sy})

    if cells:
        send_to_server({"type": "EXTINGUISH", "cells": cells, "power": 3})

    px = ff["x"] * CELL + CELL // 2
    py = ff["y"] * CELL + CELL // 2
    for i in range(1, SPRAY_LEN + 1):
        for s in range(-(i + 1), i + 2):
            if ddx == 0:
                tgx = px + s * CELL
                tgy = py + ddy * i * CELL
            else:
                tgx = px + ddx * i * CELL
                tgy = py + s * CELL
            water_particles.append({
                "x": px, "y": py,
                "vx": (tgx - px) * 0.12 + random.uniform(-1, 1),
                "vy": (tgy - py) * 0.12 + random.uniform(-1, 1),
                "tgt_x": tgx + random.uniform(-6, 6),
                "tgt_y": tgy + random.uniform(-6, 6),
                "life": 5 + i * 2,
                "max_life": 5 + i * 2,
                "sz": random.randint(1, 3),
            })


def do_shoot(ff):
    if ff["mode"] == "spray":
        do_shoot_spray(ff)
    else:
        do_shoot_stream(ff)


def tick_particles():
    dead = []
    for p in water_particles:
        if "tgt_x" in p:
            p["x"] += p["vx"] + (p["tgt_x"] - p["x"]) * 0.08
            p["y"] += p["vy"] + (p["tgt_y"] - p["y"]) * 0.08
            p["vx"] *= 0.92
            p["vy"] *= 0.92
        else:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["vy"] += 0.15
        p["life"] -= 1
        if p["life"] <= 0:
            dead.append(p)
    for p in dead:
        if p in water_particles:
            water_particles.remove(p)


def draw_particles():
    for p in water_particles:
        ratio = max(0.1, p["life"] / max(1, p["max_life"]))
        r = max(30, int(50 * ratio))
        g = max(80, int(180 * ratio))
        pygame.draw.circle(screen, (r, g, 255),
                           (int(p["x"]), int(p["y"])), p["sz"])


def draw_stream_vis(ff):
    if ff["shoot_t"] <= 0:
        return
    ddx, ddy = DIR_VEC[ff["dir"]]
    sx = ff["x"] * CELL + CELL // 2
    sy = ff["y"] * CELL + CELL // 2

    if ff["mode"] == "stream":
        ex = sx + ddx * STREAM_LEN * CELL
        ey = sy + ddy * STREAM_LEN * CELL
        for w in range(4, 0, -1):
            pygame.draw.line(screen, (50, 100 + w * 30, 255),
                             (int(sx), int(sy)),
                             (int(ex + random.randint(-3, 3)),
                              int(ey + random.randint(-3, 3))), w)
        for _ in range(2):
            pygame.draw.circle(screen, (100, 200, 255),
                               (int(ex + random.randint(-8, 8)),
                                int(ey + random.randint(-8, 8))),
                               random.randint(2, 5))
    else:
        for i in range(1, SPRAY_LEN + 1):
            spread = (i + 1) * CELL
            if ddx == 0:
                cx2 = int(sx)
                cy2 = int(sy + ddy * i * CELL)
                r1 = pygame.Rect(cx2 - spread, cy2 - CELL // 2,
                                 spread * 2, CELL)
            else:
                cx2 = int(sx + ddx * i * CELL)
                cy2 = int(sy)
                r1 = pygame.Rect(cx2 - CELL // 2, cy2 - spread,
                                 CELL, spread * 2)
            ss = pygame.Surface((r1.width, r1.height), pygame.SRCALPHA)
            alpha = max(30, 120 - i * 30)
            ss.fill((80, 160, 255, alpha))
            screen.blit(ss, r1)


def draw_combat_hose(ff):
    tx_px = ff["tx"] * CELL + CELL * 2
    ty_px = ff["ty"] * CELL + CELL * 4
    fx_px = ff["x"] * CELL + CELL // 2
    fy_px = ff["y"] * CELL + CELL // 2

    segments = 24
    points = []
    for i in range(segments + 1):
        t = i / segments
        bx = tx_px + (fx_px - tx_px) * t
        by = ty_px + (fy_px - ty_px) * t
        wave = math.sin(t * math.pi * 5) * 4 * (1 - t)
        length = math.sqrt((fx_px - tx_px) ** 2 + (fy_px - ty_px) ** 2)
        if length > 0:
            nx = -(fy_px - ty_px) / length
            ny = (fx_px - tx_px) / length
        else:
            nx = 0
            ny = 0
        bx += nx * wave
        by += ny * wave
        points.append((int(bx), int(by)))

    dist = hose_dist(ff)
    ratio = dist / HOSE_MAX_LEN
    if ratio > 0.85:
        hc = (255, 80, 80)
    elif ratio > 0.6:
        hc = (255, 200, 80)
    else:
        hc = (200, 170, 60)

    if len(points) > 1:
        pygame.draw.lines(screen, hc, False, points, 3)
        pygame.draw.lines(screen, (100, 80, 30), False, points, 1)


def draw_supply_hose(tx, ty, sx, sy):
    tx_px = tx * CELL + CELL * 2
    ty_px = ty * CELL + CELL * 4
    sx_px = sx * CELL + CELL // 2
    sy_px = sy * CELL + CELL // 2

    segments = 20
    points = []
    for i in range(segments + 1):
        t = i / segments
        bx = tx_px + (sx_px - tx_px) * t
        by = ty_px + (sy_px - ty_px) * t
        wave = math.sin(t * math.pi * 3) * 3
        length = math.sqrt((sx_px - tx_px) ** 2 + (sy_px - ty_px) ** 2)
        if length > 0:
            nx = -(sy_px - ty_px) / length
            ny = (sx_px - tx_px) / length
        else:
            nx = 0
            ny = 0
        bx += nx * wave
        by += ny * wave
        points.append((int(bx), int(by)))

    if len(points) > 1:
        pygame.draw.lines(screen, (0, 150, 255), False, points, 4)
        pygame.draw.lines(screen, (0, 80, 180), False, points, 2)

    pygame.draw.circle(screen, (0, 200, 255), (sx_px, sy_px), 5)
    pygame.draw.circle(screen, (255, 255, 255), (sx_px, sy_px), 5, 2)


def draw_ff_unit(ff, idx):
    px = int(ff["x"] * CELL) - 4
    py = int(ff["y"] * CELL) - 4
    is_act = (idx == active_ff_idx)
    d = ff["dir"]
    tkey = d + "_act" if is_act else d
    tex = ff_dir_textures.get(tkey, ff_dir_textures.get(d, ff_base_texture))
    screen.blit(tex, (px, py))

    tw = get_tw(ff["tx"], ff["ty"])
    wr = tw / TRUCK_MAX_WATER
    bw = 16
    bh = 3
    bx = px + 4
    by = py - 5
    pygame.draw.rect(screen, (50, 50, 50), (bx, by, bw, bh))
    wc = (0, 200, 255) if is_truck_supplied(ff["tx"], ff["ty"]) else (
        (0, 100, 255) if wr > 0.3 else (255, 50, 50))
    pygame.draw.rect(screen, wc, (bx, by, int(bw * wr), bh))

    ccx = int(ff["x"] * CELL) + CELL // 2
    ccy = int(ff["y"] * CELL) + CELL // 2
    adx, ady = DIR_VEC[ff["dir"]]
    arx = ccx + adx * 12
    ary = ccy + ady * 12
    ac = (255, 255, 0) if is_act else (150, 150, 150)
    pygame.draw.line(screen, ac, (ccx, ccy), (arx, ary), 2)
    pygame.draw.circle(screen, ac, (arx, ary), 3)

    mode_label = "S" if ff["mode"] == "stream" else "W"
    mode_col = (100, 200, 255) if ff["mode"] == "stream" else (200, 255, 100)
    screen.blit(font_tiny.render(mode_label, True, mode_col),
                (px + CELL + 4, py - 2))

    screen.blit(font_tiny.render(str(ff["id"]), True, (255, 255, 255)),
                (px + 6, py + CELL + 6))


def draw_grid():
    for y in range(ROWS):
        for x in range(COLS):
            fuel, intensity, ctype = server_grid[y][x]
            rect = pygame.Rect(x * CELL, y * CELL, CELL, CELL)

            if intensity > 8:
                sc = pygame.transform.scale(fire_texture, (CELL, CELL))
                screen.blit(sc, (rect.x + random.randint(-2, 2),
                                 rect.y - random.randint(2, 5)))
                continue
            if intensity > 0:
                fa = min(255, int(intensity * 28))
                fs = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
                fs.fill((255, 80, 0, fa))
                screen.blit(fs, rect)
                continue

            tk = ctype.replace("_root", "").replace("_part", "")
            if tk in TEXTURES:
                if "road" in ctype or "firecar" in ctype:
                    if "_root" in ctype:
                        screen.blit(TEXTURES[tk], rect)
                else:
                    screen.blit(TEXTURES[tk], rect)
            else:
                if ctype != "empty":
                    pygame.draw.rect(screen, (40, 40, 45), rect)

    # Supply hoses
    for (tx, ty), (sx, sy) in supply_hoses.items():
        draw_supply_hose(tx, ty, sx, sy)

    # Selected truck highlight
    if selected_truck_on_map is not None:
        stx, sty = selected_truck_on_map
        sup = is_truck_supplied(stx, sty)
        bc = (0, 255, 255) if sup else (0, 255, 0)
        pygame.draw.rect(screen, bc,
                         pygame.Rect(stx * CELL - 2, sty * CELL - 2,
                                     CELL + 4, CELL + 4), 2)
        tw = get_tw(stx, sty)
        ratio = tw / TRUCK_MAX_WATER
        bx = stx * CELL - 10
        by = sty * CELL - 14
        pygame.draw.rect(screen, (50, 50, 50), (bx, by, 60, 6))
        wbc = (0, 200, 255) if sup else (
            (0, 120, 255) if ratio > 0.2 else (255, 50, 50))
        pygame.draw.rect(screen, wbc, (bx, by, int(60 * ratio), 6))
        if sup:
            screen.blit(font_tiny.render("INF", True, (0, 255, 255)),
                        (bx + 20, by - 14))
        else:
            screen.blit(font_tiny.render(
                str(int(tw)) + "/" + str(TRUCK_MAX_WATER),
                True, (200, 200, 200)), (bx, by - 14))

    # Supply hose placement mode cursor
    if supply_hose_mode and selected_truck_on_map is not None:
        mx, my = pygame.mouse.get_pos()
        if mx < GRID_WIDTH:
            gx = mx // CELL
            gy = my // CELL
            stx, sty = selected_truck_on_map
            dist = math.sqrt((gx - stx) ** 2 + (gy - sty) ** 2)
            if 0 <= gx < COLS and 0 <= gy < ROWS:
                ct = server_grid[gy][gx][2]
                valid = ct in ("water", "hydrant") and dist <= SUPPLY_HOSE_MAX
                col = (0, 255, 100, 100) if valid else (255, 50, 50, 100)
                cs = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
                cs.fill(col)
                screen.blit(cs, (gx * CELL, gy * CELL))
                pygame.draw.rect(screen, col[:3],
                                 (gx * CELL, gy * CELL, CELL, CELL), 2)
                label = "OK" if valid else "X"
                screen.blit(font_tiny.render(label, True, col[:3]),
                            (gx * CELL + 2, gy * CELL - 12))

            # Show supply hose range circle
            cx = stx * CELL + CELL * 2
            cy = sty * CELL + CELL * 4
            radius = SUPPLY_HOSE_MAX * CELL
            pygame.draw.circle(screen, (0, 150, 255), (cx, cy), radius, 1)

    # Combat hoses
    for ff in local_firefighters:
        draw_combat_hose(ff)

    # Water streams
    for ff in local_firefighters:
        draw_stream_vis(ff)

    draw_particles()

    # Firefighter sprites
    for i, ff in enumerate(local_firefighters):
        draw_ff_unit(ff, i)

    # Server firefighters
    for f in firefighters_from_server:
        fpx = int(f.get("x", 0) * CELL) - 4
        fpy = int(f.get("y", 0) * CELL) - 4
        tex = ff_dir_textures.get("up", ff_base_texture)
        screen.blit(tex, (fpx, fpy))


truck_btn_rects = []
button_rects = {}


def draw_panel():
    global truck_btn_rects, button_rects
    truck_btn_rects = []
    button_rects = {}
    px = GRID_WIDTH

    pygame.draw.rect(screen, (20, 30, 50), (px, 0, PANEL_WIDTH, HEIGHT))
    pygame.draw.line(screen, (0, 150, 255), (px, 0), (px, HEIGHT), 2)

    y = 8
    screen.blit(font_bold.render("ROLE: " + PLAYER_ROLE.upper(),
                                 True, (0, 255, 255)), (px + 35, y))
    y += 26

    hints = [
        "--- CONTROLS ---",
        "Click truck = select",
        "TAB = switch firefighter",
        "Q = stream/spray mode",
        "WASD/Arrows = move",
        "E/F = shoot water",
        "SPACE = start/pause",
    ]
    for line in hints:
        c = (255, 220, 80) if "---" in line else (160, 170, 190)
        screen.blit(font_small.render(line, True, c), (px + 8, y))
        y += 14
    y += 4

    # Supply hose placement mode indicator
    if supply_hose_mode:
        pygame.draw.rect(screen, (0, 80, 150),
                         (px + 5, y, PANEL_WIDTH - 10, 24), border_radius=6)
        screen.blit(font_small.render(
            ">> Click water/hydrant on map <<",
            True, (0, 255, 255)), (px + 12, y + 4))
        y += 28
        cancel_btn = pygame.Rect(px + 20, y, PANEL_WIDTH - 40, 24)
        hov = cancel_btn.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(screen, (160, 30, 30) if hov else (100, 30, 30),
                         cancel_btn, border_radius=6)
        screen.blit(font_small.render("Cancel", True, (255, 255, 255)),
                    (cancel_btn.x + 80, cancel_btn.y + 3))
        button_rects["cancel_supply"] = cancel_btn
        y += 30

    if available_trucks:
        screen.blit(font_bold.render("TRUCKS:", True, (255, 220, 80)),
                    (px + 20, y))
        y += 22
        for tr in available_trucks:
            r = pygame.Rect(px + 20, y, PANEL_WIDTH - 40, 24)
            hov = r.collidepoint(pygame.mouse.get_pos())
            rc = (70, 120, 70) if hov else (35, 45, 70)
            pygame.draw.rect(screen, rc, r, border_radius=6)
            screen.blit(font_small.render(tr, True, (255, 255, 255)),
                        (r.x + 10, r.y + 4))
            truck_btn_rects.append({"rect": r, "truck": tr})
            y += 28
        y += 4

    if selected_truck_on_map is not None:
        stx, sty = selected_truck_on_map
        tw = get_tw(stx, sty)
        sup = is_truck_supplied(stx, sty)

        pygame.draw.line(screen, (0, 255, 100),
                         (px + 10, y), (px + PANEL_WIDTH - 10, y))
        y += 4
        screen.blit(font_bold.render("TRUCK SELECTED", True, (0, 255, 100)),
                    (px + 50, y))
        y += 20

        if sup:
            screen.blit(font_small.render("SUPPLY CONNECTED - INF",
                                          True, (0, 255, 255)), (px + 20, y))
        else:
            screen.blit(font_small.render(
                "Tank: " + str(int(tw)) + "/" + str(TRUCK_MAX_WATER),
                True, (100, 200, 255)), (px + 20, y))
        y += 15

        wbw = PANEL_WIDTH - 60
        wr = tw / TRUCK_MAX_WATER
        pygame.draw.rect(screen, (50, 50, 50),
                         (px + 20, y, wbw, 8), border_radius=4)
        wbc = (0, 200, 255) if sup else (
            (0, 120, 255) if wr > 0.2 else (255, 60, 60))
        pygame.draw.rect(screen, wbc,
                         (px + 20, y, int(wbw * wr), 8), border_radius=4)
        y += 14

        if not sup and not supply_hose_mode:
            shb = pygame.Rect(px + 20, y, PANEL_WIDTH - 40, 28)
            hov = shb.collidepoint(pygame.mouse.get_pos())
            pygame.draw.rect(screen,
                             (30, 120, 160) if hov else (20, 80, 120),
                             shb, border_radius=8)
            pygame.draw.rect(screen, (0, 200, 255), shb, 2, border_radius=8)
            screen.blit(font_small.render("Lay supply hose", True,
                                          (255, 255, 255)),
                        (shb.x + 40, shb.y + 5))
            button_rects["lay_supply"] = shb
            y += 34
        elif sup:
            dcb = pygame.Rect(px + 20, y, PANEL_WIDTH - 40, 24)
            hov = dcb.collidepoint(pygame.mouse.get_pos())
            pygame.draw.rect(screen,
                             (120, 40, 40) if hov else (80, 30, 30),
                             dcb, border_radius=6)
            screen.blit(font_small.render("Disconnect supply", True,
                                          (255, 180, 180)),
                        (dcb.x + 30, dcb.y + 3))
            button_rects["disconnect_supply"] = dcb
            y += 30

        sb = pygame.Rect(px + 20, y, PANEL_WIDTH - 40, 30)
        hov = sb.collidepoint(pygame.mouse.get_pos())
        sbc = (30, 160, 30) if hov else (20, 100, 20)
        pygame.draw.rect(screen, sbc, sb, border_radius=8)
        pygame.draw.rect(screen, (0, 255, 100), sb, 2, border_radius=8)
        screen.blit(font_main.render("Spawn Firefighter", True,
                                     (255, 255, 255)),
                    (sb.x + 30, sb.y + 5))
        button_rects["spawn"] = sb
        y += 38

    if local_firefighters:
        pygame.draw.line(screen, (0, 150, 255),
                         (px + 10, y), (px + PANEL_WIDTH - 10, y))
        y += 4
        screen.blit(font_bold.render("FIREFIGHTERS:", True, (0, 200, 255)),
                    (px + 20, y))
        y += 22

        for i, ff in enumerate(local_firefighters):
            is_act = (i == active_ff_idx)
            rh = 62
            r = pygame.Rect(px + 10, y, PANEL_WIDTH - 20, rh)
            bg = (40, 80, 40) if is_act else (30, 40, 60)
            pygame.draw.rect(screen, bg, r, border_radius=6)
            if is_act:
                pygame.draw.rect(screen, (0, 255, 100), r, 2,
                                 border_radius=6)

            mt = pygame.transform.scale(
                ff_dir_textures.get(ff["dir"], ff_base_texture), (18, 18))
            screen.blit(mt, (r.x + 5, r.y + 4))

            screen.blit(font_small.render(ff["name"], True, (255, 255, 255)),
                        (r.x + 28, r.y + 1))

            mode_txt = "Stream" if ff["mode"] == "stream" else "Spray"
            mode_col = (100, 200, 255) if ff["mode"] == "stream" else (200, 255, 100)
            screen.blit(font_tiny.render(
                mode_txt + " | " + ff["dir"], True, mode_col),
                (r.x + 28, r.y + 15))

            dist = hose_dist(ff)
            hose_col = (255, 80, 80) if dist > HOSE_MAX_LEN * 0.85 else (180, 180, 180)
            screen.blit(font_tiny.render(
                "Hose: {:.0f}/{}".format(dist, HOSE_MAX_LEN),
                True, hose_col), (r.x + 28, r.y + 28))

            tw = get_tw(ff["tx"], ff["ty"])
            sup = is_truck_supplied(ff["tx"], ff["ty"])
            wr = tw / TRUCK_MAX_WATER
            bbw = PANEL_WIDTH - 65
            bbx = r.x + 28
            bby = r.y + 42
            pygame.draw.rect(screen, (50, 50, 50),
                             (bbx, bby, bbw, 6), border_radius=3)
            bbc = (0, 200, 255) if sup else (
                (0, 120, 255) if wr > 0.3 else (255, 60, 60))
            pygame.draw.rect(screen, bbc,
                             (bbx, bby, int(bbw * wr), 6), border_radius=3)
            if sup:
                screen.blit(font_tiny.render("INF", True, (0, 255, 255)),
                            (bbx + bbw + 3, bby - 2))
            else:
                screen.blit(font_tiny.render(
                    str(int(tw)) + "/" + str(TRUCK_MAX_WATER),
                    True, (200, 200, 200)), (bbx + bbw + 3, bby - 2))

            st = ""
            if ff["shooting"] and ff["shoot_t"] > 0:
                st = "SHOOTING"
            elif tw <= 0 and not sup:
                st = "NO WATER!"
            if st:
                stc = (255, 80, 80) if "NO" in st else (100, 255, 100)
                screen.blit(font_tiny.render(st, True, stc),
                            (r.x + 28, r.y + 52))

            selb = pygame.Rect(r.right - 40, r.y + 3, 32, 16)
            sh = selb.collidepoint(pygame.mouse.get_pos())
            pygame.draw.rect(screen,
                             (80, 80, 180) if sh else (50, 50, 120),
                             selb, border_radius=4)
            ml = ">>>" if not is_act else "***"
            screen.blit(font_tiny.render(ml, True, (255, 255, 255)),
                        (selb.x + 3, selb.y + 1))
            button_rects["sel_" + str(i)] = selb

            y += rh + 3

    sy = HEIGHT - 28
    stxt = "SIM ON" if running_sim else "SIM OFF"
    sc = (0, 255, 0) if running_sim else (255, 100, 100)
    screen.blit(font_main.render(stxt, True, sc), (px + 20, sy))


game_running = True
current_tool = None
keys_held = set()

while game_running:
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:
            game_running = False

        elif ev.type == pygame.KEYDOWN:
            keys_held.add(ev.key)
            if ev.key == pygame.K_SPACE:
                send_to_server({"type": "SPACE"})
            elif ev.key == pygame.K_TAB:
                if local_firefighters:
                    active_ff_idx = (active_ff_idx + 1) % len(
                        local_firefighters)
            elif ev.key == pygame.K_q:
                if 0 <= active_ff_idx < len(local_firefighters):
                    ff = local_firefighters[active_ff_idx]
                    ff["mode"] = "spray" if ff["mode"] == "stream" else "stream"
            elif ev.key == pygame.K_ESCAPE:
                supply_hose_mode = False
                current_tool = None

        elif ev.type == pygame.KEYUP:
            keys_held.discard(ev.key)

        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            mx, my = ev.pos

            if mx < GRID_WIDTH:
                gx = mx // CELL
                gy = my // CELL

                if supply_hose_mode and selected_truck_on_map is not None:
                    stx, sty = selected_truck_on_map
                    dist = math.sqrt((gx - stx) ** 2 + (gy - sty) ** 2)
                    if (0 <= gx < COLS and 0 <= gy < ROWS
                            and dist <= SUPPLY_HOSE_MAX):
                        ct = server_grid[gy][gx][2]
                        if ct in ("water", "hydrant"):
                            send_to_server({
                                "type": "LAY_SUPPLY_HOSE",
                                "tx": stx, "ty": sty,
                                "sx": gx, "sy": gy
                            })
                            supply_hose_mode = False
                elif current_tool:
                    send_to_server({"type": "PLACE_TRUCK",
                                    "x": gx, "y": gy,
                                    "truck": current_tool})
                    current_tool = None
                else:
                    placed = find_trucks_on_map()
                    clicked_tr = None
                    for t in placed:
                        if abs(t[0] - gx) <= 2 and abs(t[1] - gy) <= 4:
                            clicked_tr = t
                            break
                    if clicked_tr:
                        selected_truck_on_map = clicked_tr
                    else:
                        clicked_ff = False
                        for i, ff in enumerate(local_firefighters):
                            if (abs(ff["x"] - gx) <= 1
                                    and abs(ff["y"] - gy) <= 1):
                                active_ff_idx = i
                                clicked_ff = True
                                break
                        if not clicked_ff:
                            selected_truck_on_map = None
            else:
                # Panel clicks
                for tb in truck_btn_rects:
                    if tb["rect"].collidepoint(ev.pos):
                        current_tool = tb["truck"]
                        break

                if "spawn" in button_rects:
                    if button_rects["spawn"].collidepoint(ev.pos):
                        if selected_truck_on_map is not None:
                            nf = spawn_ff(selected_truck_on_map[0],
                                          selected_truck_on_map[1])
                            if nf:
                                local_firefighters.append(nf)
                                active_ff_idx = len(local_firefighters) - 1
                                send_to_server({
                                    "type": "SPAWN_FIREFIGHTER",
                                    "id": nf["id"],
                                    "x": nf["x"],
                                    "y": nf["y"],
                                })

                if "lay_supply" in button_rects:
                    if button_rects["lay_supply"].collidepoint(ev.pos):
                        supply_hose_mode = True

                if "cancel_supply" in button_rects:
                    if button_rects["cancel_supply"].collidepoint(ev.pos):
                        supply_hose_mode = False

                if "disconnect_supply" in button_rects:
                    if button_rects["disconnect_supply"].collidepoint(ev.pos):
                        if selected_truck_on_map is not None:
                            stx, sty = selected_truck_on_map
                            send_to_server({
                                "type": "DISCONNECT_SUPPLY",
                                "tx": stx, "ty": sty
                            })
                            if (stx, sty) in supply_hoses:
                                del supply_hoses[(stx, sty)]

                for i in range(len(local_firefighters)):
                    k = "sel_" + str(i)
                    if k in button_rects:
                        if button_rects[k].collidepoint(ev.pos):
                            active_ff_idx = i
                            break

    # Movement
    if 0 <= active_ff_idx < len(local_firefighters):
        ff = local_firefighters[active_ff_idx]
        dx = 0.0
        dy = 0.0
        moved = False

        if pygame.K_LEFT in keys_held or pygame.K_a in keys_held:
            dx -= FF_SPEED
            ff["dir"] = "left"
            moved = True
        if pygame.K_RIGHT in keys_held or pygame.K_d in keys_held:
            dx += FF_SPEED
            ff["dir"] = "right"
            moved = True
        if pygame.K_UP in keys_held or pygame.K_w in keys_held:
            dy -= FF_SPEED
            ff["dir"] = "up"
            moved = True
        if pygame.K_DOWN in keys_held or pygame.K_s in keys_held:
            dy += FF_SPEED
            ff["dir"] = "down"
            moved = True

        if dx != 0 and dy != 0:
            dx *= 0.707
            dy *= 0.707

        nx = ff["x"] + dx
        ny = ff["y"] + dy

        if can_walk(int(nx), int(ff["y"])) and check_hose(ff, nx, ff["y"]):
            ff["x"] = max(0.0, min(float(COLS - 1), nx))
        if can_walk(int(ff["x"]), int(ny)) and check_hose(ff, ff["x"], ny):
            ff["y"] = max(0.0, min(float(ROWS - 1), ny))

        if moved:
            send_to_server({
                "type": "MOVE_FIREFIGHTER",
                "id": ff["id"],
                "x": ff["x"],
                "y": ff["y"],
            })

        if pygame.K_e in keys_held or pygame.K_f in keys_held:
            if ff["cd"] <= 0:
                do_shoot(ff)

    for ff in local_firefighters:
        if ff["cd"] > 0:
            ff["cd"] -= 1
        if ff["shoot_t"] > 0:
            ff["shoot_t"] -= 1
        if ff["shoot_t"] <= 0:
            ff["shooting"] = False

    tick_particles()

    screen.fill((5, 10, 20))
    draw_grid()
    draw_panel()
    pygame.display.flip()
    clock.tick(FPS)

pygame.quit()
try:
    sock.close()
except Exception:
    pass