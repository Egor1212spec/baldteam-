import os
import sys
import json
import socket
import struct
import threading
import random
import pygame

def recv_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk: return None
        data += chunk
    return data

def run_game(initial_grid, server_ip, server_port, password, my_role):
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    pygame.display.set_caption(f"Песочница пожара — ИГРА [{my_role.upper()}]")
    clock = pygame.time.Clock()

    grid = [row[:] for row in initial_grid]   # копия карты

    # ================= СИМУЛЯЦИЯ ГОРЕНИЯ =================
    def simulate_burning():
        nonlocal grid
        new_grid = [row[:] for row in grid]
        for y in range(len(grid)):
            for x in range(len(grid[0])):
                fuel, intensity, ctype = grid[y][x]
                if intensity > 0:
                    # горение распространяется
                    intensity += random.randint(1, 3)
                    if intensity > 100:
                        intensity = 100
                    # передаём огонь соседям
                    for dy, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < len(grid) and 0 <= nx < len(grid[0]):
                            nf, ni, nc = new_grid[ny][nx]
                            if nc in ("tree", "grass", "wood") and ni == 0 and random.random() < 0.4:
                                new_grid[ny][nx] = [nf, random.randint(10, 30), nc]
                    new_grid[y][x] = [fuel - 1, intensity, ctype]
        grid = new_grid

    # ================= СЕТЬ =================
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect((server_ip, server_port))
    # авторизация (можно упростить, т.к. уже подключались)
    # ...

    def network_thread():
        while True:
            try:
                raw = recv_exact(client, 4)
                if not raw: break
                msglen = struct.unpack('>I', raw)[0]
                data = recv_exact(client, msglen)
                msg = json.loads(data.decode('utf-8'))
                if "grid" in msg:
                    grid[:] = msg["grid"]
            except:
                break

    threading.Thread(target=network_thread, daemon=True).start()

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        simulate_burning()          # ← симуляция горения каждый кадр
        # draw_grid() — твой код отрисовки (перенеси сюда из client.py)

        pygame.display.flip()
        clock.tick(30)

    client.close()
    pygame.quit()