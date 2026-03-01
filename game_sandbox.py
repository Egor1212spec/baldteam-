import os
import sys
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
selected_unit = None
selected_truck_on_map = None  # координаты выбранной машины на карте

# --- Локальные пожарные (управляемые игроком) ---
local_firefighters = []  # список: {"id", "x", "y", "truck_name", "water", "max_water", "spray_cooldown"}
active_firefighter_idx = -1  # индекс активного пожарного
next_ff_id = 1

FIREFIGHTER_SPEED = 0.15  # клеток за кадр
SPRAY_RADIUS = 2  # радиус тушения в клетках
SPRAY_COOLDOWN_MAX = 10  # кадров между тушениями
WATER_PER_SPRAY = 5
MAX_WATER = 200

# Частицы воды для визуализации
water_particles = []


def get_ui_font(size, bold=False):
    font_paths = [
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return pygame.font.Font(path, size)
            except Exception:
                pass
    return pygame.font.SysFont("arial", size, bold=bold)


def recv_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def send_to_server(data):
    try:
        msg = json.dumps(data).encode("utf-8")
        sock.sendall(struct.pack(">I", len(msg)) + msg)
    except:
        pass


pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption(f"ПЕСОЧНИЦА ПОЖАРА - {PLAYER_ROLE.upper()}")
clock = pygame.time.Clock()

font_main = get_ui_font(18)
font_bold = get_ui_font(20, True)
small_font = get_ui_font(14)
tiny_font = get_ui_font(12)

TEXTURES = {}
fire_texture = None


def load_textures():
    global TEXTURES, fire_texture
    os.makedirs(TEXTURE_DIR, exist_ok=True)
    TEXTURES = {}
    try:
        fire_texture = pygame.image.load(
            os.path.join(BASE_DIR, "fire.png")
        ).convert_alpha()
    except Exception:
        fire_texture = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
        fire_texture.fill((255, 100, 0, 180))

    for filename in os.listdir(TEXTURE_DIR):
        if not filename.lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        key = os.path.splitext(filename)[0].lower()
        path = os.path.join(TEXTURE_DIR, filename)
        try:
            img = pygame.image.load(path).convert_alpha()
            if key in ("firecar",):
                TEXTURES["firecar"] = pygame.transform.scale(img, (64, 128))
            elif key in ("road", "road_straight"):
                TEXTURES["road"] = pygame.transform.scale(img, (CELL * 4, CELL * 4))
            elif key in ("road_right", "road_turn"):
                TEXTURES["road_right"] = pygame.transform.scale(
                    img, (CELL * 5, CELL * 5)
                )
            else:
                TEXTURES[key] = pygame.transform.scale(img, (CELL, CELL))
        except Exception as e:
            print(f"Error loading {filename}: {e}")


load_textures()

server_grid = [[[0, 0, "empty"] for _ in range(COLS)] for _ in range(ROWS)]
running_sim = False
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
connected = False

try:
    sock.connect((SERVER_IP, SERVER_PORT))
    auth = {"type": "AUTH", "password": SERVER_PASSWORD, "role": PLAYER_ROLE}
    msg = json.dumps(auth).encode("utf-8")
    sock.sendall(struct.pack(">I", len(msg)) + msg)
    connected = True
except:
    pass


def receive_thread():
    global server_grid, running_sim, available_trucks, firefighters_from_server
    while True:
        try:
            raw = recv_exact(sock, 4)
            if not raw:
                break
            mlen = struct.unpack(">I", raw)[0]
            data = json.loads(recv_exact(sock, mlen).decode("utf-8"))
            msg_type = data.get("type")
            if msg_type == "STATE_UPDATE":
                server_grid = data["grid"]
                running_sim = data.get("running_sim", False)
                available_trucks = data.get("available_trucks", [])
                firefighters_from_server = data.get("firefighters", [])
            elif msg_type == "TRUCK_AVAILABLE":
                available_trucks = data.get("available", [])
            elif msg_type == "CREW_UPDATE":
                firefighters_from_server = data.get("firefighters", [])
        except:
            break


if connected:
    threading.Thread(target=receive_thread, daemon=True).start()


# --- Вспомогательные функции ---

def find_placed_trucks():
    """Ищет все машины (firecar) размещённые на карте."""
    trucks = []
    for y in range(ROWS):
        for x in range(COLS):
            cell = server_grid[y][x]
            ctype = cell[2] if len(cell) > 2 else ""
            if "firecar" in ctype and "_root" in ctype:
                trucks.append({"x": x, "y": y, "type": ctype})
    return trucks


def is_passable(gx, gy):
    """Проверяет, может ли пожарный пройти в клетку."""
    if gx < 0 or gy < 0 or gx >= COLS or gy >= ROWS:
        return False
    cell = server_grid[int(gy)][int(gx)]
    intensity = cell[1]
    # Нельзя ходить в сильный огонь
    if intensity > 6:
        return False
    return True


def spawn_firefighter_from_truck(truck_x, truck_y):
    """Создаёт пожарного рядом с машиной."""
    global next_ff_id
    # Ищем свободную клетку рядом с машиной
    for dy in range(-2, 5):
        for dx in range(-2, 5):
            nx, ny = truck_x + dx, truck_y + dy
            if 0 <= nx < COLS and 0 <= ny < ROWS:
                cell = server_grid[ny][nx]
                ctype = cell[2] if len(cell) > 2 else ""
                if cell[1] < 3 and "firecar" not in ctype:
                    ff = {
                        "id": next_ff_id,
                        "x": float(nx),
                        "y": float(ny),
                        "truck_name": f"Пожарный #{next_ff_id}",
                        "water": MAX_WATER,
                        "max_water": MAX_WATER,
                        "spray_cooldown": 0,
                        "source_truck_x": truck_x,
                        "source_truck_y": truck_y,
                        "spraying": False,
                    }
                    next_ff_id += 1
                    return ff
    return None


def spray_water(ff):
    """Пожарный тушит огонь вокруг себя."""
    if ff["water"] <= 0 or ff["spray_cooldown"] > 0:
        return
    ff["spray_cooldown"] = SPRAY_COOLDOWN_MAX
    ff["water"] = max(0, ff["water"] - WATER_PER_SPRAY)
    ff["spraying"] = True

    cx, cy = int(ff["x"]), int(ff["y"])
    # Отправляем серверу команду тушения
    cells_to_extinguish = []
    for dy in range(-SPRAY_RADIUS, SPRAY_RADIUS + 1):
        for dx in range(-SPRAY_RADIUS, SPRAY_RADIUS + 1):
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < COLS and 0 <= ny < ROWS:
                if dx * dx + dy * dy <= SPRAY_RADIUS * SPRAY_RADIUS:
                    cell = server_grid[ny][nx]
                    if cell[1] > 0:
                        cells_to_extinguish.append({"x": nx, "y": ny})

    if cells_to_extinguish:
        send_to_server({
            "type": "EXTINGUISH",
            "cells": cells_to_extinguish,
            "power": 3,
        })

    # Создаём частицы воды
    for _ in range(20):
        angle = random.uniform(0, 2 * math.pi)
        dist = random.uniform(0.5, SPRAY_RADIUS) * CELL
        water_particles.append({
            "x": ff["x"] * CELL + CELL // 2,
            "y": ff["y"] * CELL + CELL // 2,
            "vx": math.cos(angle) * dist * 0.15,
            "vy": math.sin(angle) * dist * 0.15,
            "life": random.randint(8, 20),
            "size": random.randint(2, 4),
        })


def refill_water(ff):
    """Пополнить воду если рядом с машиной."""
    tx, ty = ff["source_truck_x"], ff["source_truck_y"]
    dist = abs(ff["x"] - tx) + abs(ff["y"] - ty)
    if dist < 4:
        ff["water"] = min(ff["max_water"], ff["water"] + 3)
        return True
    return False


def update_water_particles():
    """Обновляет частицы воды."""
    for p in water_particles[:]:
        p["x"] += p["vx"]
        p["y"] += p["vy"]
        p["life"] -= 1
        p["vy"] += 0.2  # гравитация
        if p["life"] <= 0:
            water_particles.remove(p)


def draw_water_particles():
    """Рисует частицы воды."""
    for p in water_particles:
        alpha = max(30, int(255 * p["life"] / 20))
        color = (50, 100 + random.randint(0, 50), 255)
        pygame.draw.circle(screen, color, (int(p["x"]), int(p["y"])), p["size"])


# --- Отрисовка ---

def draw_grid():
    for y in range(ROWS):
        for x in range(COLS):
            fuel, intensity, ctype = server_grid[y][x]
            rect = pygame.Rect(x * CELL, y * CELL, CELL, CELL)

            if intensity > 8:
                scaled = pygame.transform.scale(fire_texture, (CELL, CELL))
                screen.blit(
                    scaled,
                    (rect.x + random.randint(-2, 2), rect.y - random.randint(2, 5)),
                )
                continue

            # Подсветка огня средней интенсивности
            if intensity > 0:
                fire_alpha = min(255, intensity * 28)
                fire_surf = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
                fire_surf.fill((255, 80, 0, fire_alpha))
                screen.blit(fire_surf, rect)
                continue

            t_key = ctype.replace("_root", "").replace("_part", "")
            if t_key in TEXTURES:
                if "road" in ctype or "firecar" in ctype:
                    if "_root" in ctype:
                        screen.blit(TEXTURES[t_key], rect)
                else:
                    screen.blit(TEXTURES[t_key], rect)
            else:
                if ctype != "empty":
                    pygame.draw.rect(screen, (40, 40, 45), rect)

    # Подсветка выбранной машины
    if selected_truck_on_map is not None:
        tx, ty = selected_truck_on_map
        highlight = pygame.Surface((CELL * 4, CELL * 8), pygame.SRCALPHA)
        highlight.fill((0, 255, 0, 40))
        screen.blit(highlight, (tx * CELL - CELL, ty * CELL - CELL))
        pygame.draw.rect(
            screen, (0, 255, 0),
            pygame.Rect(tx * CELL - 2, ty * CELL - 2, CELL + 4, CELL + 4), 2,
        )

    # Рисуем локальных пожарных
    for i, ff in enumerate(local_firefighters):
        px = int(ff["x"] * CELL)
        py = int(ff["y"] * CELL)

        is_active = i == active_firefighter_idx

        # Тень
        pygame.draw.circle(screen, (0, 0, 0, 80), (px + CELL // 2, py + CELL // 2 + 2), 8)

        # Тело
        body_color = (255, 255, 0) if is_active else (0, 200, 255)
        pygame.draw.circle(screen, body_color, (px + CELL // 2, py + CELL // 2), 7)

        # Обводка
        outline_color = (255, 255, 255) if is_active else (100, 100, 100)
        pygame.draw.circle(screen, outline_color, (px + CELL // 2, py + CELL // 2), 8, 2)

        # Каска (маленький треугольник сверху)
        pygame.draw.polygon(screen, (200, 50, 50), [
            (px + CELL // 2, py - 2),
            (px + CELL // 2 - 4, py + 5),
            (px + CELL // 2 + 4, py + 5),
        ])

        # Полоска воды над головой
        bar_w = 14
        bar_h = 3
        bar_x = px + CELL // 2 - bar_w // 2
        bar_y = py - 6
        water_ratio = ff["water"] / ff["max_water"] if ff["max_water"] > 0 else 0
        pygame.draw.rect(screen, (50, 50, 50), (bar_x, bar_y, bar_w, bar_h))
        bar_color = (0, 100, 255) if water_ratio > 0.3 else (255, 50, 50)
        pygame.draw.rect(screen, bar_color, (bar_x, bar_y, int(bar_w * water_ratio), bar_h))

        # Индикатор тушения
        if ff["spraying"] and ff["spray_cooldown"] > SPRAY_COOLDOWN_MAX // 2:
            radius = SPRAY_RADIUS * CELL
            spray_surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(spray_surf, (50, 150, 255, 40), (radius, radius), radius)
            pygame.draw.circle(spray_surf, (50, 150, 255, 80), (radius, radius), radius, 2)
            screen.blit(spray_surf, (px + CELL // 2 - radius, py + CELL // 2 - radius))

        # Номер
        num_surf = tiny_font.render(str(ff["id"]), True, (255, 255, 255))
        screen.blit(num_surf, (px + CELL // 2 - num_surf.get_width() // 2, py + CELL + 1))

    # Серверные пожарные
    for f in firefighters_from_server:
        px = int(f["x"] * CELL)
        py = int(f["y"] * CELL)
        color = (0, 100, 255) if f.get("id") == selected_unit else (0, 200, 255)
        pygame.draw.circle(screen, color, (px + CELL // 2, py + CELL // 2), 7)
        pygame.draw.circle(screen, (255, 255, 255), (px + CELL // 2, py + CELL // 2), 7, 2)

    # Рисуем частицы воды поверх всего
    draw_water_particles()


last_truck_rects = []
last_button_rects = {}


def draw_panel():
    global last_truck_rects, last_button_rects
    last_truck_rects = []
    last_button_rects = {}
    panel_x = GRID_WIDTH
    pygame.draw.rect(screen, (20, 30, 50), (panel_x, 0, PANEL_WIDTH, HEIGHT))
    pygame.draw.line(screen, (0, 150, 255), (panel_x, 0), (panel_x, HEIGHT), 2)

    y = 15
    title = font_bold.render(f"РОЛЬ: {PLAYER_ROLE.upper()}", True, (0, 255, 255))
    screen.blit(title, (panel_x + 35, y))
    y += 35

    # Подсказки управления
    controls_lines = [
        "─── УПРАВЛЕНИЕ ───",
        "Клик по машине → выбрать",
        "Кнопка → призвать пожарного",
        "TAB → переключить пожарного",
        "WASD/стрелки → движение",
        "E/F → тушить огонь",
        "R → пополнить воду (у машины)",
        "SPACE → старт/пауза",
    ]
    for line in controls_lines:
        color = (255, 220, 80) if "───" in line else (170, 180, 200)
        screen.blit(small_font.render(line, True, color), (panel_x + 10, y))
        y += 18
    y += 10

    # Доступная техника (от диспетчера)
    if available_trucks:
        header = font_bold.render("ТЕХНИКА:", True, (255, 220, 80))
        screen.blit(header, (panel_x + 20, y))
        y += 30

        for truck in available_trucks:
            rect = pygame.Rect(panel_x + 20, y, PANEL_WIDTH - 40, 32)
            hover = rect.collidepoint(pygame.mouse.get_pos())
            color = (70, 120, 70) if hover else (35, 45, 70)
            pygame.draw.rect(screen, color, rect, border_radius=6)
            screen.blit(
                small_font.render(truck, True, (255, 255, 255)),
                (rect.x + 12, rect.y + 8),
            )
            last_truck_rects.append({"rect": rect, "truck": truck})
            y += 36
        y += 10

    # Кнопка призвать пожарного (если выбрана машина)
    if selected_truck_on_map is not None:
        pygame.draw.line(screen, (0, 255, 100), (panel_x + 10, y), (panel_x + PANEL_WIDTH - 10, y))
        y += 10
        sel_text = font_bold.render("МАШИНА ВЫБРАНА", True, (0, 255, 100))
        screen.blit(sel_text, (panel_x + 50, y))
        y += 30

        spawn_btn = pygame.Rect(panel_x + 20, y, PANEL_WIDTH - 40, 36)
        hover = spawn_btn.collidepoint(pygame.mouse.get_pos())
        btn_color = (30, 160, 30) if hover else (20, 100, 20)
        pygame.draw.rect(screen, btn_color, spawn_btn, border_radius=8)
        pygame.draw.rect(screen, (0, 255, 100), spawn_btn, 2, border_radius=8)
        btn_text = font_main.render("🚒 Призвать пожарного", True, (255, 255, 255))
        screen.blit(btn_text, (spawn_btn.x + 15, spawn_btn.y + 8))
        last_button_rects["spawn_ff"] = spawn_btn
        y += 45

    # Список пожарных
    if local_firefighters:
        pygame.draw.line(screen, (0, 150, 255), (panel_x + 10, y), (panel_x + PANEL_WIDTH - 10, y))
        y += 10
        ff_header = font_bold.render("ПОЖАРНЫЕ:", True, (0, 200, 255))
        screen.blit(ff_header, (panel_x + 20, y))
        y += 28

        for i, ff in enumerate(local_firefighters):
            is_active = i == active_firefighter_idx
            rect = pygame.Rect(panel_x + 15, y, PANEL_WIDTH - 30, 50)

            # Фон карточки
            bg_color = (40, 80, 40) if is_active else (30, 40, 60)
            pygame.draw.rect(screen, bg_color, rect, border_radius=6)
            if is_active:
                pygame.draw.rect(screen, (0, 255, 100), rect, 2, border_radius=6)

            # Иконка
            icon_color = (255, 255, 0) if is_active else (0, 200, 255)
            pygame.draw.circle(screen, icon_color, (rect.x + 16, rect.y + 16), 8)
            pygame.draw.circle(screen, (255, 255, 255), (rect.x + 16, rect.y + 16), 8, 2)

            # Имя
            name = small_font.render(ff["truck_name"], True, (255, 255, 255))
            screen.blit(name, (rect.x + 30, rect.y + 4))

            # Полоска воды
            water_ratio = ff["water"] / ff["max_water"]
            bar_w = PANEL_WIDTH - 80
            bar_x = rect.x + 30
            bar_y = rect.y + 24
            pygame.draw.rect(screen, (50, 50, 50), (bar_x, bar_y, bar_w, 8), border_radius=3)
            bar_color = (0, 120, 255) if water_ratio > 0.3 else (255, 60, 60)
            pygame.draw.rect(screen, bar_color, (bar_x, bar_y, int(bar_w * water_ratio), 8), border_radius=3)

            # Текст воды
            water_text = tiny_font.render(f"{ff['water']}/{ff['max_water']}", True, (200, 200, 200))
            screen.blit(water_text, (bar_x + bar_w + 5, bar_y - 2))

            # Статус
            status = ""
            if ff["water"] <= 0:
                status = "НЕТ ВОДЫ!"
            elif ff["spraying"]:
                status = "ТУШИТ"
            status_color = (255, 80, 80) if ff["water"] <= 0 else (100, 255, 100)
            if status:
                st = tiny_font.render(status, True, status_color)
                screen.blit(st, (rect.x + 30, rect.y + 36))

            # Кнопка выбора
            sel_btn = pygame.Rect(rect.right - 50, rect.y + 5, 40, 20)
            sel_hover = sel_btn.collidepoint(pygame.mouse.get_pos())
            sel_bg = (80, 80, 180) if sel_hover else (50, 50, 120)
            pygame.draw.rect(screen, sel_bg, sel_btn, border_radius=4)
            sel_label = tiny_font.render("▶" if not is_active else "●", True, (255, 255, 255))
            screen.blit(sel_label, (sel_btn.x + 12, sel_btn.y + 2))
            last_button_rects[f"select_ff_{i}"] = sel_btn

            y += 55

    # Статус симуляции
    y = HEIGHT - 40
    status_text = "● СИМУЛЯЦИЯ ИДЁТ" if running_sim else "○ СИМУЛЯЦИЯ НА ПАУЗЕ"
    status_color = (0, 255, 0) if running_sim else (255, 100, 100)
    screen.blit(font_main.render(status_text, True, status_color), (panel_x + 20, y))


running = True
current_tool = None
keys_pressed = set()

while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.KEYDOWN:
            keys_pressed.add(event.key)

            if event.key == pygame.K_SPACE:
                send_to_server({"type": "SPACE"})

            # Переключение пожарных по TAB
            if event.key == pygame.K_TAB and local_firefighters:
                active_firefighter_idx = (active_firefighter_idx + 1) % len(local_firefighters)

            # Тушение огня — E или F
            if event.key in (pygame.K_e, pygame.K_f):
                if 0 <= active_firefighter_idx < len(local_firefighters):
                    spray_water(local_firefighters[active_firefighter_idx])

            # Пополнение воды — R
            if event.key == pygame.K_r:
                if 0 <= active_firefighter_idx < len(local_firefighters):
                    refill_water(local_firefighters[active_firefighter_idx])

        if event.type == pygame.KEYUP:
            keys_pressed.discard(event.key)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos

            if mx < GRID_WIDTH:
                gx, gy = mx // CELL, my // CELL

                if current_tool:
                    send_to_server(
                        {"type": "PLACE_TRUCK", "x": gx, "y": gy, "truck": current_tool}
                    )
                    current_tool = None
                else:
                    # Проверяем клик по машине на карте
                    placed_trucks = find_placed_trucks()
                    clicked_truck = None
                    for t in placed_trucks:
                        # Машина может быть многоклеточной, проверяем область
                        if abs(t["x"] - gx) <= 2 and abs(t["y"] - gy) <= 4:
                            clicked_truck = (t["x"], t["y"])
                            break

                    if clicked_truck:
                        selected_truck_on_map = clicked_truck
                    else:
                        # Проверяем клик по локальному пожарному
                        clicked_ff = False
                        for i, ff in enumerate(local_firefighters):
                            if abs(ff["x"] - gx) <= 1 and abs(ff["y"] - gy) <= 1:
                                active_firefighter_idx = i
                                clicked_ff = True
                                break

                        if not clicked_ff:
                            selected_truck_on_map = None
            else:
                # Панель
                for btn in last_truck_rects:
                    if btn["rect"].collidepoint(event.pos):
                        current_tool = btn["truck"]

                # Кнопка призвать пожарного
                if "spawn_ff" in last_button_rects:
                    if last_button_rects["spawn_ff"].collidepoint(event.pos):
                        if selected_truck_on_map is not None:
                            ff = spawn_firefighter_from_truck(
                                selected_truck_on_map[0], selected_truck_on_map[1]
                            )
                            if ff:
                                local_firefighters.append(ff)
                                active_firefighter_idx = len(local_firefighters) - 1
                                # Уведомляем сервер
                                send_to_server({
                                    "type": "SPAWN_FIREFIGHTER",
                                    "id": ff["id"],
                                    "x": ff["x"],
                                    "y": ff["y"],
                                })

                # Кнопки выбора пожарных
                for i in range(len(local_firefighters)):
                    key = f"select_ff_{i}"
                    if key in last_button_rects and last_button_rects[key].collidepoint(event.pos):
                        active_firefighter_idx = i

    # --- Движение активного пожарного ---
    if 0 <= active_firefighter_idx < len(local_firefighters):
        ff = local_firefighters[active_firefighter_idx]
        dx, dy = 0, 0

        if pygame.K_LEFT in keys_pressed or pygame.K_a in keys_pressed:
            dx -= FIREFIGHTER_SPEED
        if pygame.K_RIGHT in keys_pressed or pygame.K_d in keys_pressed:
            dx += FIREFIGHTER_SPEED
        if pygame.K_UP in keys_pressed or pygame.K_w in keys_pressed:
            dy -= FIREFIGHTER_SPEED
        if pygame.K_DOWN in keys_pressed or pygame.K_s in keys_pressed:
            dy += FIREFIGHTER_SPEED

        # Нормализация диагонального движения
        if dx != 0 and dy != 0:
            factor = 0.707
            dx *= factor
            dy *= factor

        new_x = ff["x"] + dx
        new_y = ff["y"] + dy

        # Проверка границ и проходимости
        if is_passable(int(new_x), int(ff["y"])):
            ff["x"] = max(0, min(COLS - 1, new_x))
        if is_passable(int(ff["x"]), int(new_y)):
            ff["y"] = max(0, min(ROWS - 1, new_y))

        # Обновляем позицию на сервере
        if dx != 0 or dy != 0:
            send_to_server({
                "type": "MOVE_FIREFIGHTER",
                "id": ff["id"],
                "x": ff["x"],
                "y": ff["y"],
            })

    # --- Обновление кулдаунов и состояний ---
    for ff in local_firefighters:
        if ff["spray_cooldown"] > 0:
            ff["spray_cooldown"] -= 1
        if ff["spray_cooldown"] <= 0:
            ff["spraying"] = False

        # Автоматическая заправка рядом с машиной
        refill_water(ff)

    # Непрерывное тушение (удержание E/F)
    if (pygame.K_e in keys_pressed or pygame.K_f in keys_pressed):
        if 0 <= active_firefighter_idx < len(local_firefighters):
            ff = local_firefighters[active_firefighter_idx]
            if ff["spray_cooldown"] <= 0:
                spray_water(ff)

    # Обновляем частицы
    update_water_particles()

    screen.fill((5, 10, 20))
    draw_grid()
    draw_panel()
    pygame.display.flip()
    clock.tick(FPS)

pygame.quit()
sock.close()