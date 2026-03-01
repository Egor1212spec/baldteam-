import socket
import threading
import json
import struct
import time
import random
import math
import os

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if load_dotenv is not None:
    load_dotenv(os.path.join(BASE_DIR, ".env"))

HOST = os.getenv("SERVER_HOST", "127.0.0.1")
PORT = int(os.getenv("SERVER_PORT", "5555"))
MAX_PLAYERS = int(os.getenv("MAX_PLAYERS", "6"))
SERVER_PASSWORD = os.getenv("SERVER_PASSWORD", "my_super_password")

COLS = 60
ROWS = 44
UPDATE_EVERY = 60
SUPPLY_HOSE_MAX = 15

TRUCKS = [
    "АЦ-40", "АЦ-3,2-40/4", "АЦ-6,0-40", "ПНС-110",
    "АР-2", "АНР-3,0-100", "АЛ-30", "АЛ-50"
]


class Cell:
    def __init__(self):
        self.fuel = 0
        self.intensity = 0
        self.type = "empty"
        self.heat = 0.0
        self.moisture = 22.0
        self.state = "unburned"


grid = [[Cell() for _ in range(COLS)] for _ in range(ROWS)]
edit_mode = True
running_sim = False
frame = 0
available_trucks = []
server_firefighters = []
supply_connections = []  # [[tx, ty, sx, sy], ...]

clients = []
client_roles = {}
grid_lock = threading.Lock()

ALLOWED_ROLES = {"rtp", "nsh", "br", "dispatcher"}

WIND = (1, -3)
WIND_STRENGTH = 2.15

FUEL_PROPERTIES = {
    "grass":          {"ign_temp": 42,   "burn_rate": 3.8,  "heat_gen": 58,   "spread_mult": 1.85},
    "trunk":          {"ign_temp": 65,   "burn_rate": 0.72, "heat_gen": 52,   "spread_mult": 1.45},
    "foliage":        {"ign_temp": 38,   "burn_rate": 4.2,  "heat_gen": 138,  "spread_mult": 0.8},
    "wall":           {"ign_temp": 72,   "burn_rate": 0.95, "heat_gen": 78,   "spread_mult": 0.7},
    "floor":          {"ign_temp": 48,   "burn_rate": 2.2,  "heat_gen": 70,   "spread_mult": 1.4},
    "stone":          {"ign_temp": 9999, "burn_rate": 0,    "heat_gen": 0,    "spread_mult": 0},
    "water":          {"ign_temp": 9999, "burn_rate": 0,    "heat_gen": 0,    "spread_mult": 0},
    "concrete":       {"ign_temp": 9999, "burn_rate": 0,    "heat_gen": 0,    "spread_mult": 0},
    "hydrant":        {"ign_temp": 140,  "burn_rate": 0.4,  "heat_gen": 35,   "spread_mult": 0.3},
    "wood_floor":     {"ign_temp": 45,   "burn_rate": 2.8,  "heat_gen": 75,   "spread_mult": 1.6},
    "firecar_root":   {"ign_temp": 9999, "burn_rate": 0,    "heat_gen": 0,    "spread_mult": 0},
    "firecar_part":   {"ign_temp": 9999, "burn_rate": 0,    "heat_gen": 0,    "spread_mult": 0},
    "road_turn_root": {"ign_temp": 9999, "burn_rate": 0,    "heat_gen": 0,    "spread_mult": 0},
    "road_turn_part": {"ign_temp": 9999, "burn_rate": 0,    "heat_gen": 0,    "spread_mult": 0},
}


def get_props(cell_type):
    return FUEL_PROPERTIES.get(cell_type, FUEL_PROPERTIES["grass"])


def place_stamp(x, y, tool):
    if not (0 <= x < COLS and 0 <= y < ROWS):
        return

    if tool == "tree":
        trunk_height = 12
        for dy in range(trunk_height):
            ny = y + dy
            if ny >= ROWS:
                break
            c = grid[ny][x]
            c.type = "trunk"
            c.fuel = random.randint(175, 235)
            c.moisture = random.uniform(9, 19)
            c.heat = 0.0
            c.state = "unburned"
            c.intensity = 0
        crown_base = y + trunk_height - 6
        for layer in range(8):
            radius = 7 - layer // 2
            for dy in range(-radius - 1, radius + 2):
                for dx in range(-radius - 1, radius + 2):
                    if abs(dx) + abs(dy) > radius + random.random() * 1.8:
                        continue
                    nx2 = x + dx
                    ny2 = crown_base - layer + dy
                    if not (0 <= nx2 < COLS and 0 <= ny2 < ROWS):
                        continue
                    c = grid[ny2][nx2]
                    if c.type == "trunk":
                        continue
                    c.type = "foliage"
                    c.fuel = random.randint(68, 118)
                    c.moisture = random.uniform(28, 48)
                    c.heat = 0.0
                    c.state = "unburned"
                    c.intensity = 0

    elif tool == "grass":
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                nx2 = x + dx
                ny2 = y + dy
                if 0 <= nx2 < COLS and 0 <= ny2 < ROWS:
                    c = grid[ny2][nx2]
                    c.type = "grass"
                    c.fuel = random.randint(28, 55)
                    c.moisture = random.uniform(18, 35)
                    c.heat = 0
                    c.state = "unburned"

    elif tool == "lake":
        size = 9
        for dy in range(-size, size + 1):
            for dx in range(-size, size + 1):
                if dx * dx + dy * dy <= size * size + random.randint(-5, 5):
                    nx2 = x + dx
                    ny2 = y + dy
                    if 0 <= nx2 < COLS and 0 <= ny2 < ROWS:
                        c = grid[ny2][nx2]
                        c.type = "water"
                        c.fuel = 0
                        c.intensity = 0
                        c.moisture = 100
                        c.state = "burned"

    elif tool == "house":
        for dy in range(-6, 7):
            for dx in range(-9, 10):
                nx2 = x + dx
                ny2 = y + dy
                if 0 <= nx2 < COLS and 0 <= ny2 < ROWS:
                    c = grid[ny2][nx2]
                    if abs(dy) == 6 or abs(dx) == 9:
                        c.type = "wall"
                        c.fuel = random.randint(200, 255)
                    else:
                        c.type = "floor"
                        c.fuel = random.randint(100, 155)
                    c.moisture = 12
                    c.heat = 0
                    c.state = "unburned"

    elif tool == "wall":
        c = grid[y][x]
        c.type = "wall"
        c.fuel = 230
        c.moisture = 10
        c.state = "unburned"

    elif tool == "floor":
        c = grid[y][x]
        c.type = "floor"
        c.fuel = 130
        c.moisture = 15
        c.state = "unburned"

    elif tool == "stone":
        c = grid[y][x]
        c.type = "stone"
        c.fuel = 0
        c.moisture = 0
        c.state = "burned"

    elif tool == "ignite":
        c = grid[y][x]
        if c.fuel <= 10:
            c.fuel = 60
        c.intensity = random.randint(45, 72)
        c.heat = 92.0
        c.state = "burning"
        c.moisture = 4.0

    elif tool == "concrete":
        c = grid[y][x]
        c.type = "concrete"
        c.fuel = 0
        c.moisture = 0
        c.state = "burned"

    elif tool == "hydrant":
        c = grid[y][x]
        c.type = "hydrant"
        c.fuel = random.randint(8, 25)
        c.moisture = 5
        c.state = "unburned"

    elif tool == "wood_floor":
        c = grid[y][x]
        c.type = "floor"
        c.fuel = random.randint(140, 190)
        c.moisture = 12
        c.state = "unburned"

    elif tool == "road_straight":
        w, h = 4, 4
        if x + w <= COLS and y + h <= ROWS:
            for dy in range(h):
                for dx in range(w):
                    c = grid[y + dy][x + dx]
                    if dx == 0 and dy == 0:
                        c.type = "road_straight_root"
                    else:
                        c.type = "road_straight_part"
                    c.fuel = 0
                    c.moisture = 0
                    c.intensity = 0
                    c.state = "burned"

    elif tool == "road_turn":
        w, h = 5, 5
        if x + w <= COLS and y + h <= ROWS:
            for dy in range(h):
                for dx in range(w):
                    c = grid[y + dy][x + dx]
                    if dx == 0 and dy == 0:
                        c.type = "road_turn_root"
                    else:
                        c.type = "road_turn_part"
                    c.fuel = 0
                    c.moisture = 0
                    c.intensity = 0
                    c.state = "burned"

    elif tool in TRUCKS or tool == "firecar":
        w, h = 4, 8
        if x + w <= COLS and y + h <= ROWS:
            for dy in range(h):
                for dx in range(w):
                    c = grid[y + dy][x + dx]
                    if dx == 0 and dy == 0:
                        c.type = "firecar_root"
                    else:
                        c.type = "firecar_part"
                    c.fuel = 0
                    c.moisture = 0
                    c.intensity = 0
                    c.state = "burned"
            if tool in available_trucks:
                available_trucks.remove(tool)
                broadcast({"type": "TRUCK_AVAILABLE",
                           "available": available_trucks[:]})


def extinguish_cells(cells, power):
    for ci in cells:
        cx = ci.get("x", -1)
        cy = ci.get("y", -1)
        if 0 <= cx < COLS and 0 <= cy < ROWS:
            c = grid[cy][cx]
            c.intensity = max(0, c.intensity - power * 12)
            c.heat = max(0, c.heat - power * 40)
            c.moisture = min(100, c.moisture + power * 20)
            c.fuel = max(0, c.fuel - power * 3)
            if c.intensity <= 0:
                c.intensity = 0
                c.heat = 0
                c.state = "smoldering"


def update_fire():
    if not running_sim:
        return

    heat_map = [[0.0] * COLS for _ in range(ROWS)]

    for y in range(ROWS):
        for x in range(COLS):
            c = grid[y][x]
            heat_map[y][x] = c.heat * 0.67
            if c.intensity <= 8:
                continue
            props = get_props(c.type)
            heat_out = props["heat_gen"] * (c.intensity / 55.0)

            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    if dx == 0 and dy == 0:
                        continue
                    nx2 = x + dx
                    ny2 = y + dy
                    if nx2 < 0 or nx2 >= COLS or ny2 < 0 or ny2 >= ROWS:
                        continue
                    dist = max(1.0, (abs(dx) + abs(dy)) ** 0.72)
                    heat = heat_out / dist
                    wind_bias = (dx * WIND[0] + dy * WIND[1]) * WIND_STRENGTH * 0.65
                    if dy < 0:
                        vb = 1.5
                    elif dy > 0:
                        vb = 1.0
                    else:
                        vb = 1.2
                    heat_map[ny2][nx2] += (heat + wind_bias) * vb

            c.fuel = max(0, c.fuel - props["burn_rate"] * (c.intensity / 80.0))
            c.intensity = max(0, c.intensity - 0.4)

    for y in range(ROWS):
        for x in range(COLS):
            c = grid[y][x]
            if c.type == "water":
                c.heat = 0
                continue
            c.heat = heat_map[y][x]
            if c.moisture > 50:
                c.heat *= 0.85
            if c.state in ("unburned", "smoldering") and c.fuel > 16:
                props = get_props(c.type)
                ign_temp = props["ign_temp"]
                if c.type == "foliage":
                    bt = False
                    for cy2 in range(y + 1, min(ROWS, y + 7)):
                        for cx2 in range(max(0, x - 2), min(COLS, x + 3)):
                            tc = grid[cy2][cx2]
                            if tc.type == "trunk" and tc.intensity > 15:
                                bt = True
                                break
                        if bt:
                            break
                    if not bt:
                        ign_temp *= 2.85
                final_ign = ign_temp * (1.0 + c.moisture / 80.0)
                if c.heat > final_ign:
                    c.intensity = random.randint(33, 59)
                    c.state = "burning"
                    c.moisture = max(0, c.moisture - 24)

    for y in range(ROWS):
        for x in range(COLS):
            c = grid[y][x]
            if c.fuel <= 8:
                c.intensity = 0
                if c.state != "burned":
                    c.state = "smoldering" if c.fuel > 3 else "burned"
                c.heat *= 0.52
            if c.moisture > 22:
                c.moisture -= 0.3


def recv_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def send_msg(sock, data):
    try:
        msg = json.dumps(data).encode("utf-8")
        sock.sendall(struct.pack(">I", len(msg)) + msg)
    except Exception:
        pass


def broadcast(data):
    payload = json.dumps(data).encode("utf-8")
    packet = struct.pack(">I", len(payload)) + payload
    dead = []
    for c in clients[:]:
        try:
            c.sendall(packet)
        except Exception:
            dead.append(c)
    for c in dead:
        if c in clients:
            clients.remove(c)
        if c in client_roles:
            del client_roles[c]


def client_thread(conn, addr):
    global edit_mode, running_sim, grid
    addr_str = str(addr)

    try:
        conn.settimeout(10.0)
        raw_len = recv_exact(conn, 4)
        if not raw_len:
            conn.close()
            return
        msg_len = struct.unpack(">I", raw_len)[0]
        raw_data = recv_exact(conn, msg_len)
        if not raw_data:
            conn.close()
            return

        auth = json.loads(raw_data.decode("utf-8"))
        if auth.get("type") != "AUTH" or auth.get("password") != SERVER_PASSWORD:
            send_msg(conn, {"type": "AUTH_FAIL", "reason": "Bad password"})
            conn.close()
            return

        role = auth.get("role", "").lower()
        if role not in ALLOWED_ROLES:
            send_msg(conn, {"type": "AUTH_FAIL", "reason": "Bad role"})
            conn.close()
            return

        send_msg(conn, {"type": "AUTH_OK", "role": role})
        conn.settimeout(None)

        with grid_lock:
            clients.append(conn)
            client_roles[conn] = role

        print("[+] {} joined as {} | Players: {}".format(
            addr, role, len(clients)))

        with grid_lock:
            net_grid = [[[c.fuel, c.intensity, c.type] for c in row]
                        for row in grid]
            send_msg(conn, {
                "type": "STATE_UPDATE",
                "grid": net_grid,
                "edit_mode": edit_mode,
                "running_sim": running_sim,
                "available_trucks": available_trucks[:],
                "firefighters": server_firefighters[:],
                "supply_hoses": supply_connections[:]
            })

        while True:
            raw_len = recv_exact(conn, 4)
            if not raw_len:
                break
            msg_len = struct.unpack(">I", raw_len)[0]
            raw_data = recv_exact(conn, msg_len)
            if not raw_data:
                break

            try:
                cmd = json.loads(raw_data.decode("utf-8"))
            except Exception:
                continue

            cmd_type = cmd.get("type", "")

            with grid_lock:
                if cmd_type == "CLICK":
                    place_stamp(cmd.get("x", 0), cmd.get("y", 0),
                                cmd.get("tool", ""))

                elif cmd_type == "FILL_BASE":
                    tool = cmd.get("tool", "")
                    for yy in range(ROWS):
                        for xx in range(COLS):
                            c = grid[yy][xx]
                            if c.type in ("empty", "grass", "floor", "stone"):
                                if tool == "empty":
                                    c.type = "empty"
                                    c.fuel = 0
                                elif tool == "grass":
                                    c.type = "grass"
                                    c.fuel = random.randint(28, 55)
                                elif tool == "floor":
                                    c.type = "floor"
                                    c.fuel = 130
                                elif tool == "stone":
                                    c.type = "stone"
                                    c.fuel = 0
                                c.intensity = 0
                                c.heat = 0
                                c.moisture = 25 if tool == "grass" else 15
                                c.state = "unburned"

                elif cmd_type == "SPACE":
                    if edit_mode:
                        edit_mode = False
                        running_sim = True
                    else:
                        running_sim = not running_sim

                elif cmd_type == "R":
                    grid = [[Cell() for _ in range(COLS)] for _ in range(ROWS)]
                    edit_mode = True
                    running_sim = False
                    supply_connections.clear()

                elif cmd_type == "LOAD_MAP":
                    received = cmd.get("grid")
                    if received and len(received) == ROWS:
                        ok = all(len(row) == COLS for row in received)
                        if ok:
                            for yy in range(ROWS):
                                for xx in range(COLS):
                                    cd = received[yy][xx]
                                    c = grid[yy][xx]
                                    c.fuel = cd[0]
                                    c.intensity = cd[1]
                                    c.type = cd[2]
                                    c.heat = 0.0
                                    c.moisture = 15.0
                                    c.state = ("burning" if cd[1] > 0
                                               else "unburned")
                            edit_mode = True
                            running_sim = False
                            supply_connections.clear()

                elif cmd_type == "HOST_READY":
                    fg = cmd.get("final_grid")
                    if fg and len(fg) == ROWS:
                        ok = all(len(row) == COLS for row in fg)
                        if ok:
                            for yy in range(ROWS):
                                for xx in range(COLS):
                                    fuel, intensity, ctype = fg[yy][xx]
                                    c = grid[yy][xx]
                                    c.fuel = fuel
                                    c.intensity = intensity
                                    c.type = ctype
                                    c.heat = 0
                                    c.moisture = (22 if ctype in
                                                  ("grass", "tree") else 0)
                                    c.state = ("unburned" if intensity == 0
                                               else "burning")
                            edit_mode = False
                            running_sim = False
                            supply_connections.clear()
                            broadcast({
                                "type": "START_GAME",
                                "grid": fg,
                                "message": "Game started!"
                            })

                elif cmd_type == "DEPLOY_TRUCK":
                    truck = cmd.get("truck")
                    if truck and truck in TRUCKS:
                        available_trucks.append(truck)
                        broadcast({
                            "type": "TRUCK_AVAILABLE",
                            "truck": truck,
                            "available": available_trucks[:]
                        })

                elif cmd_type == "PLACE_TRUCK":
                    place_stamp(cmd.get("x", 0), cmd.get("y", 0),
                                cmd.get("truck", ""))

                elif cmd_type == "SPAWN_FIREFIGHTER":
                    server_firefighters.append({
                        "id": cmd.get("id", 0),
                        "x": cmd.get("x", 0),
                        "y": cmd.get("y", 0),
                        "owner": addr_str
                    })

                elif cmd_type == "MOVE_FIREFIGHTER":
                    ff_id = cmd.get("id")
                    for ff in server_firefighters:
                        if ff["id"] == ff_id and ff["owner"] == addr_str:
                            ff["x"] = cmd.get("x", 0)
                            ff["y"] = cmd.get("y", 0)
                            break

                elif cmd_type == "MOVE_UNIT":
                    uid = cmd.get("id")
                    for ff in server_firefighters:
                        if ff["id"] == uid:
                            ff["x"] = cmd.get("x", 0)
                            ff["y"] = cmd.get("y", 0)
                            break

                elif cmd_type == "EXTINGUISH":
                    extinguish_cells(cmd.get("cells", []),
                                     cmd.get("power", 3))

                elif cmd_type == "LAY_SUPPLY_HOSE":
                    tx = cmd.get("tx", 0)
                    ty = cmd.get("ty", 0)
                    sx = cmd.get("sx", 0)
                    sy = cmd.get("sy", 0)

                    already = False
                    for sc in supply_connections:
                        if sc[0] == tx and sc[1] == ty:
                            already = True
                            break

                    if not already:
                        dist = math.sqrt((sx - tx) ** 2 + (sy - ty) ** 2)
                        valid_source = False
                        if (0 <= sx < COLS and 0 <= sy < ROWS):
                            ct = grid[sy][sx].type
                            if ct in ("water", "hydrant"):
                                valid_source = True

                        if valid_source and dist <= SUPPLY_HOSE_MAX:
                            supply_connections.append([tx, ty, sx, sy])
                            send_msg(conn, {
                                "type": "SUPPLY_OK",
                                "tx": tx, "ty": ty,
                                "sx": sx, "sy": sy
                            })
                            print("[+] Supply hose: truck({},{}) -> {}({},{})".format(
                                tx, ty, grid[sy][sx].type, sx, sy))
                        else:
                            send_msg(conn, {
                                "type": "SUPPLY_FAIL",
                                "tx": tx, "ty": ty,
                                "reason": "Too far or no water source"
                            })

                elif cmd_type == "DISCONNECT_SUPPLY":
                    tx = cmd.get("tx", 0)
                    ty = cmd.get("ty", 0)
                    to_rm = []
                    for sc in supply_connections:
                        if sc[0] == tx and sc[1] == ty:
                            to_rm.append(sc)
                    for sc in to_rm:
                        supply_connections.remove(sc)
                    print("[-] Supply hose disconnected: ({},{})".format(
                        tx, ty))

    except Exception as e:
        print("[!] Error {}: {}".format(addr, e))
    finally:
        to_rm = [ff for ff in server_firefighters
                 if ff.get("owner") == addr_str]
        for ff in to_rm:
            server_firefighters.remove(ff)
        if conn in clients:
            clients.remove(conn)
        if conn in client_roles:
            del client_roles[conn]
        try:
            conn.close()
        except Exception:
            pass
        print("[-] {} left | Players: {}".format(addr, len(clients)))


def game_loop():
    global frame
    while True:
        try:
            with grid_lock:
                if running_sim and frame % UPDATE_EVERY == 0:
                    try:
                        update_fire()
                    except Exception as e:
                        print("Fire error: {}".format(e))
                frame += 1

                net_grid = [[[c.fuel, c.intensity, c.type] for c in row]
                            for row in grid]
                state = {
                    "type": "STATE_UPDATE",
                    "grid": net_grid,
                    "edit_mode": edit_mode,
                    "running_sim": running_sim,
                    "available_trucks": available_trucks[:],
                    "firefighters": server_firefighters[:],
                    "supply_hoses": supply_connections[:]
                }
            broadcast(state)
        except Exception as e:
            print("Loop error: {}".format(e))

        time.sleep(1.0 / 33.0)


if __name__ == "__main__":
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(MAX_PLAYERS)

    print("Server on {}:{}".format(HOST, PORT))
    print("Fire: UPDATE_EVERY={}".format(UPDATE_EVERY))
    print("Supply hose max: {} cells".format(SUPPLY_HOSE_MAX))

    threading.Thread(target=game_loop, daemon=True).start()

    while True:
        try:
            conn, addr = server.accept()
            if len(clients) >= MAX_PLAYERS:
                conn.close()
            else:
                threading.Thread(target=client_thread,
                                 args=(conn, addr),
                                 daemon=True).start()
        except Exception as e:
            print("Accept error: {}".format(e))