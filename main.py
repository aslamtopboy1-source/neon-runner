"""
NEON RUNNER — Professional-style 2D platformer starter project
==============================================================
Built with Python 3 + Pygame. All visuals are drawn procedurally; no external
art/audio assets are required.

Controls
--------
A / Left Arrow       Move left
D / Right Arrow      Move right
W / Up / Space       Jump (hold for a slightly higher jump)
S / Down Arrow       Fast-fall
Left Shift           Sprint
E                    Interact with checkpoint / portal
P / Escape           Pause / resume
R                    Restart level
F1                   Toggle debug overlay
M                    Toggle procedural music-like ambience
Enter                Start / continue
Mouse                Navigate title / game-over menus

Run
---
python -m pip install pygame
python main.py

This is a single-file game architecture designed to be easy to expand.
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import pygame


# =============================================================================
# Configuration
# =============================================================================

TITLE = "NEON RUNNER"
VERSION = "1.0.0"
SCREEN_WIDTH = 1100
SCREEN_HEIGHT = 680
FPS = 60
TILE = 40
GRAVITY = 1900.0
PLAYER_ACCEL = 2300.0
PLAYER_FRICTION = 1900.0
PLAYER_MAX_SPEED = 340.0
PLAYER_SPRINT_SPEED = 465.0
PLAYER_JUMP_SPEED = 690.0
PLAYER_MAX_FALL = 1050.0
COYOTE_TIME = 0.115
JUMP_BUFFER_TIME = 0.13
SAVE_FILE = Path.home() / ".neon_runner_save.json"

# Palette
INK = (9, 11, 28)
DEEP_BLUE = (15, 21, 48)
PANEL = (20, 28, 58)
CYAN = (62, 238, 255)
MAGENTA = (255, 67, 190)
YELLOW = (255, 221, 92)
WHITE = (237, 245, 255)
MUTED = (132, 153, 190)
GREEN = (92, 255, 174)
RED = (255, 83, 108)
PURPLE = (144, 103, 255)
ORANGE = (255, 151, 75)

pygame.init()
pygame.display.set_caption(f"{TITLE} v{VERSION}")
SCREEN = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
CLOCK = pygame.time.Clock()


# =============================================================================
# Small utility helpers
# =============================================================================

def clamp(value: float, low: float, high: float) -> float:
    """Clamp a number to a closed interval."""
    return max(low, min(high, value))


def sign(value: float) -> int:
    """Return -1, 0, or 1."""
    return (value > 0) - (value < 0)


def lerp(a: float, b: float, amount: float) -> float:
    """Linear interpolation."""
    return a + (b - a) * amount


def ease_out(value: float) -> float:
    """Simple cubic ease-out for UI animation."""
    value = clamp(value, 0.0, 1.0)
    return 1.0 - (1.0 - value) ** 3


def vec_length(x: float, y: float) -> float:
    return math.sqrt(x * x + y * y)


def draw_text(surface: pygame.Surface, text: str, size: int, color: tuple,
              x: float, y: float, *, center: bool = False,
              font_name: Optional[str] = None) -> pygame.Rect:
    """Render text with a consistent font and optional center alignment."""
    font = pygame.font.SysFont(font_name or "consolas", size, bold=True)
    image = font.render(str(text), True, color)
    rect = image.get_rect()
    if center:
        rect.center = (int(x), int(y))
    else:
        rect.topleft = (int(x), int(y))
    surface.blit(image, rect)
    return rect


def draw_panel(surface: pygame.Surface, rect: pygame.Rect,
               fill: tuple = PANEL, border: tuple = CYAN,
               radius: int = 12, width: int = 2) -> None:
    """Draw a translucent-looking panel with a neon outline."""
    pygame.draw.rect(surface, fill, rect, border_radius=radius)
    pygame.draw.rect(surface, border, rect, width, border_radius=radius)


def load_save() -> dict:
    """Load best score and unlocked level, recovering safely from bad files."""
    defaults = {"best_score": 0, "unlocked_level": 1, "total_coins": 0}
    try:
        if SAVE_FILE.exists():
            with SAVE_FILE.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            for key in defaults:
                if key in data:
                    defaults[key] = max(0, int(data[key]))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return defaults


def save_progress(data: dict) -> None:
    """Persist progress; a save failure must not crash the game."""
    try:
        SAVE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = SAVE_FILE.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        temp.replace(SAVE_FILE)
    except OSError:
        # The game remains playable if the home directory is read-only.
        pass


def draw_glow(surface: pygame.Surface, center: tuple, radius: int,
              color: tuple, alpha: int = 50) -> None:
    """Cheap soft glow using concentric translucent circles."""
    diameter = max(2, radius * 2)
    glow = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
    for ring in range(5, 0, -1):
        r = max(1, int(radius * ring / 5))
        a = int(alpha * (1.0 - ring / 6.0))
        pygame.draw.circle(glow, (*color, a), (radius, radius), r)
    surface.blit(glow, (int(center[0] - radius), int(center[1] - radius)))


# =============================================================================
# Particles and background
# =============================================================================

@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    color: tuple
    size: float
    gravity: float = 0.0

    def update(self, dt: float) -> None:
        self.life -= dt
        self.vy += self.gravity * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.size = max(0.2, self.size - dt * 2.4)

    def draw(self, surface: pygame.Surface, camera_x: float = 0) -> None:
        if self.life <= 0:
            return
        fade = clamp(self.life / max(0.001, self.max_life), 0, 1)
        radius = max(1, int(self.size))
        color = tuple(int(c * fade) for c in self.color)
        pygame.draw.circle(surface, color,
                           (int(self.x - camera_x), int(self.y)), radius)


class ParticleSystem:
    """Centralized particles for jump dust, collectibles and enemy bursts."""

    def __init__(self) -> None:
        self.items: list[Particle] = []

    def emit(self, x: float, y: float, color: tuple, count: int = 8,
             speed: float = 170, life: float = 0.45,
             gravity: float = 350, size: float = 3.0) -> None:
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            velocity = random.uniform(speed * 0.25, speed)
            self.items.append(Particle(
                x, y, math.cos(angle) * velocity,
                math.sin(angle) * velocity, life * random.uniform(0.65, 1.2),
                life, color, random.uniform(size * 0.5, size), gravity
            ))

    def update(self, dt: float) -> None:
        for particle in self.items:
            particle.update(dt)
        self.items = [p for p in self.items if p.life > 0]

    def draw(self, surface: pygame.Surface, camera_x: float = 0) -> None:
        for particle in self.items:
            particle.draw(surface, camera_x)


class Starfield:
    """Parallax star layers and distant geometric skyline."""

    def __init__(self) -> None:
        self.stars = []
        for layer, amount in enumerate((55, 45, 35)):
            for _ in range(amount):
                self.stars.append({
                    "x": random.uniform(0, 4200),
                    "y": random.uniform(20, SCREEN_HEIGHT * 0.76),
                    "r": random.choice((1, 1, 2)),
                    "layer": layer,
                    "phase": random.uniform(0, math.tau),
                })
        self.buildings = []
        x = -20
        while x < 4600:
            width = random.randint(35, 95)
            height = random.randint(80, 250)
            self.buildings.append((x, width, height))
            x += width + random.randint(5, 24)

    def draw(self, surface: pygame.Surface, camera_x: float, tick: float) -> None:
        surface.fill(INK)
        # Atmospheric bands
        for y in range(0, SCREEN_HEIGHT, 4):
            t = y / SCREEN_HEIGHT
            c = (int(10 + t * 5), int(13 + t * 8), int(32 + t * 17))
            pygame.draw.line(surface, c, (0, y), (SCREEN_WIDTH, y))
        # Stars move at different speeds to make the world feel deep.
        for star in self.stars:
            factor = (0.08, 0.17, 0.30)[star["layer"]]
            sx = int((star["x"] - camera_x * factor) % (SCREEN_WIDTH + 100))
            sy = int(star["y"])
            shimmer = 0.6 + 0.4 * math.sin(tick * 2.2 + star["phase"])
            color = (int(80 * shimmer), int(145 * shimmer), int(210 * shimmer))
            pygame.draw.circle(surface, color, (sx, sy), star["r"])
        # Skyline silhouette
        for bx, width, height in self.buildings:
            sx = int(bx - camera_x * 0.42) % (SCREEN_WIDTH + 160) - 80
            base = SCREEN_HEIGHT - 55
            rect = pygame.Rect(sx, base - height, width, height + 60)
            pygame.draw.rect(surface, (13, 20, 45), rect)
            pygame.draw.line(surface, (28, 50, 82), rect.topleft,
                             (rect.right, rect.top), 2)
            for wy in range(rect.top + 14, base - 5, 24):
                for wx in range(rect.left + 9, rect.right - 4, 18):
                    if (wx * 7 + wy * 3) % 5 == 0:
                        pygame.draw.rect(surface, (30, 80, 110),
                                         (wx, wy, 4, 7))
        # Horizon glow
        glow = pygame.Surface((SCREEN_WIDTH, 120), pygame.SRCALPHA)
        pygame.draw.ellipse(glow, (20, 160, 220, 22),
                            (-100, 45, SCREEN_WIDTH + 200, 100))
        surface.blit(glow, (0, SCREEN_HEIGHT - 160))


# =============================================================================
# Level data
# =============================================================================

@dataclass
class Platform:
    rect: pygame.Rect
    kind: str = "solid"
    moving: bool = False
    start_x: float = 0
    start_y: float = 0
    move_range: float = 0
    move_speed: float = 0
    phase: float = 0
    previous_rect: Optional[pygame.Rect] = None

    def __post_init__(self) -> None:
        self.start_x = float(self.rect.x)
        self.start_y = float(self.rect.y)
        self.previous_rect = self.rect.copy()

    def update(self, dt: float, elapsed: float) -> None:
        self.previous_rect = self.rect.copy()
        if self.moving:
            offset = math.sin(elapsed * self.move_speed + self.phase) * self.move_range
            self.rect.x = int(self.start_x + offset)

    def draw(self, surface: pygame.Surface, camera_x: float) -> None:
        r = self.rect.move(-int(camera_x), 0)
        if r.right < -30 or r.left > SCREEN_WIDTH + 30:
            return
        if self.kind == "danger":
            pygame.draw.rect(surface, (80, 20, 58), r, border_radius=5)
            pygame.draw.line(surface, RED, r.topleft, r.topright, 4)
            for x in range(r.left + 8, r.right, 18):
                pygame.draw.line(surface, (255, 100, 125),
                                 (x, r.top + 8), (x + 8, r.bottom - 5), 2)
        elif self.kind == "bounce":
            pygame.draw.rect(surface, (29, 76, 80), r, border_radius=5)
            pygame.draw.line(surface, GREEN, r.topleft, r.topright, 4)
            for x in range(r.left + 8, r.right - 4, 15):
                pygame.draw.line(surface, GREEN,
                                 (x, r.top + 7), (x + 7, r.bottom - 6), 2)
        else:
            pygame.draw.rect(surface, (22, 37, 72), r, border_radius=4)
            pygame.draw.line(surface, CYAN, r.topleft, r.topright, 3)
            pygame.draw.line(surface, (35, 80, 112),
                             r.bottomleft, r.bottomright, 2)
            # Small glowing studs
            for x in range(r.left + 12, r.right - 4, 28):
                pygame.draw.circle(surface, (70, 145, 170), (x, r.top + 9), 2)


@dataclass
class Coin:
    x: float
    y: float
    taken: bool = False
    phase: float = 0.0

    def update(self, dt: float) -> None:
        self.phase += dt * 5

    def draw(self, surface: pygame.Surface, camera_x: float) -> None:
        if self.taken:
            return
        x = int(self.x - camera_x)
        y = int(self.y + math.sin(self.phase) * 5)
        if -30 <= x <= SCREEN_WIDTH + 30:
            draw_glow(surface, (x, y), 18, YELLOW, 48)
            pygame.draw.circle(surface, YELLOW, (x, y), 8)
            pygame.draw.circle(surface, (255, 250, 190), (x - 2, y - 2), 3)
            pygame.draw.circle(surface, (170, 112, 35), (x, y), 8, 2)


@dataclass
class Hazard:
    rect: pygame.Rect
    kind: str = "laser"
    phase: float = 0.0
    active: bool = True

    def update(self, dt: float) -> None:
        self.phase += dt
        if self.kind == "pulse":
            self.active = math.sin(self.phase * 2.4) > -0.25

    def draw(self, surface: pygame.Surface, camera_x: float) -> None:
        r = self.rect.move(-int(camera_x), 0)
        if r.right < 0 or r.left > SCREEN_WIDTH:
            return
        if self.kind == "laser":
            pygame.draw.rect(surface, (55, 20, 62), r, border_radius=4)
            if self.active:
                pygame.draw.rect(surface, MAGENTA, r.inflate(-8, -5),
                                 border_radius=3)
                pygame.draw.line(surface, (255, 220, 255),
                                 (r.left + 4, r.centery),
                                 (r.right - 4, r.centery), 2)
        else:
            color = RED if self.active else (75, 43, 66)
            pygame.draw.polygon(surface, color, [
                (r.left, r.bottom), (r.centerx, r.top), (r.right, r.bottom)
            ])
            pygame.draw.line(surface, (255, 210, 220),
                             (r.centerx, r.top + 5), (r.centerx, r.bottom - 4), 2)


@dataclass
class Checkpoint:
    x: float
    y: float
    activated: bool = False
    phase: float = 0.0

    def update(self, dt: float) -> None:
        self.phase += dt * 3

    def draw(self, surface: pygame.Surface, camera_x: float) -> None:
        x = int(self.x - camera_x)
        y = int(self.y)
        if -60 < x < SCREEN_WIDTH + 60:
            color = GREEN if self.activated else PURPLE
            draw_glow(surface, (x, y - 22), 28, color, 50)
            pygame.draw.line(surface, color, (x, y + 12), (x, y - 45), 4)
            pygame.draw.polygon(surface, color, [
                (x + 2, y - 42), (x + 25, y - 34), (x + 2, y - 25)
            ])
            pygame.draw.circle(surface, WHITE if self.activated else color,
                               (x, y - 22 + int(math.sin(self.phase) * 3)), 5)


@dataclass
class Portal:
    x: float
    y: float
    radius: int = 26
    phase: float = 0.0

    def update(self, dt: float) -> None:
        self.phase += dt * 2.2

    def draw(self, surface: pygame.Surface, camera_x: float) -> None:
        x, y = int(self.x - camera_x), int(self.y)
        if -70 < x < SCREEN_WIDTH + 70:
            radius = self.radius + int(math.sin(self.phase) * 3)
            draw_glow(surface, (x, y), 58, CYAN, 65)
            pygame.draw.ellipse(surface, (25, 68, 100),
                                (x - radius, y - radius * 1.35,
                                 radius * 2, radius * 2.7))
            pygame.draw.ellipse(surface, CYAN,
                                (x - radius, y - radius * 1.35,
                                 radius * 2, radius * 2.7), 4)
            pygame.draw.ellipse(surface, WHITE,
                                (x - radius + 7, y - radius * 1.35 + 7,
                                 radius * 2 - 14, radius * 2.7 - 14), 1)


@dataclass
class Enemy:
    x: float
    y: float
    left_bound: float
    right_bound: float
    speed: float = 100.0
    direction: int = 1
    alive: bool = True
    phase: float = 0.0
    width: int = 34
    height: int = 30

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x - self.width / 2),
                           int(self.y - self.height / 2),
                           self.width, self.height)

    def update(self, dt: float) -> None:
        if not self.alive:
            return
        self.phase += dt * 7
        self.x += self.speed * self.direction * dt
        if self.x < self.left_bound:
            self.x = self.left_bound
            self.direction = 1
        elif self.x > self.right_bound:
            self.x = self.right_bound
            self.direction = -1

    def draw(self, surface: pygame.Surface, camera_x: float) -> None:
        if not self.alive:
            return
        r = self.rect.move(-int(camera_x), 0)
        if r.right < 0 or r.left > SCREEN_WIDTH:
            return
        bob = int(math.sin(self.phase) * 3)
        body = r.move(0, bob)
        draw_glow(surface, body.center, 24, MAGENTA, 30)
        pygame.draw.rect(surface, (70, 25, 76), body, border_radius=8)
        pygame.draw.rect(surface, MAGENTA, body, 2, border_radius=8)
        pygame.draw.circle(surface, WHITE, (body.centerx - 6, body.centery - 2), 3)
        pygame.draw.circle(surface, WHITE, (body.centerx + 6, body.centery - 2), 3)
        pygame.draw.line(surface, (255, 140, 224),
                         (body.left + 6, body.bottom - 3),
                         (body.right - 6, body.bottom - 3), 2)


class Level:
    """Owns the geometry and collectible/enemy objects for one stage."""

    def __init__(self, number: int) -> None:
        self.number = number
        self.name = ("BOOT SEQUENCE", "THE GLASS DISTRICT",
                     "REACTOR RUN", "SKYLINE ZERO")[min(number - 1, 3)]
        self.width = 3900 + (number - 1) * 650
        self.platforms: list[Platform] = []
        self.coins: list[Coin] = []
        self.hazards: list[Hazard] = []
        self.enemies: list[Enemy] = []
        self.checkpoints: list[Checkpoint] = []
        self.portal = Portal(self.width - 110, 455)
        self.spawn = (90.0, 500.0)
        self._build()

    def _platform(self, x: int, y: int, w: int, h: int = 24,
                  kind: str = "solid", moving: bool = False,
                  move_range: float = 0, move_speed: float = 1.0,
                  phase: float = 0) -> None:
        self.platforms.append(Platform(
            pygame.Rect(x, y, w, h), kind, moving,
            move_range=move_range, move_speed=move_speed, phase=phase
        ))

    def _coin_line(self, x: int, y: int, count: int, spacing: int = 36) -> None:
        for i in range(count):
            self.coins.append(Coin(x + i * spacing, y, phase=i * 0.7))

    def _build(self) -> None:
        # The ground is split into sections to create visible gaps.
        self._platform(0, 590, 520, 90)
        self._platform(610, 590, 390, 90)
        self._platform(1090, 590, 420, 90)
        self._platform(1610, 590, 370, 90)
        self._platform(2080, 590, 420, 90)
        self._platform(2600, 590, 430, 90)
        self._platform(3130, 590, self.width - 3130, 90)

        # Ascending and descending routes.
        self._platform(300, 485, 150)
        self._platform(530, 420, 130, moving=True, move_range=40,
                       move_speed=1.3, phase=0.4)
        self._platform(760, 355, 150)
        self._platform(970, 440, 100)
        self._platform(1170, 500, 120)
        self._platform(1370, 420, 130, moving=True, move_range=55,
                       move_speed=1.1, phase=1.5)
        self._platform(1570, 345, 150)
        self._platform(1800, 430, 120)
        self._platform(1980, 500, 120)
        self._platform(2220, 420, 140)
        self._platform(2440, 345, 130)
        self._platform(2670, 450, 130)
        self._platform(2870, 380, 150)
        self._platform(3090, 470, 130)
        self._platform(3340, 410, 160)
        self._platform(3570, 330, 170)
        self._platform(self.width - 320, 500, 180, kind="bounce")

        # Additional stage length and optional alternate platforms.
        for index in range(4, self.number + 3):
            base = 3900 + (index - 4) * 500
            if base < self.width - 300:
                self._platform(base, 510 - (index % 3) * 45, 130,
                               moving=(index % 2 == 0),
                               move_range=45, move_speed=1.0 + index * 0.08,
                               phase=index * 0.5)

        self._coin_line(320, 445, 4)
        self._coin_line(560, 375, 3)
        self._coin_line(780, 310, 4)
        self._coin_line(1190, 455, 3)
        self._coin_line(1390, 375, 3)
        self._coin_line(1590, 300, 4)
        self._coin_line(2240, 375, 3)
        self._coin_line(2460, 300, 3)
        self._coin_line(2890, 335, 4)
        self._coin_line(3360, 365, 4)
        self._coin_line(3590, 285, 4)
        self._coin_line(self.width - 300, 445, 3)

        # Lethal spikes and laser bars.
        self.hazards.extend([
            Hazard(pygame.Rect(700, 565, 78, 25), "spikes"),
            Hazard(pygame.Rect(1235, 565, 85, 25), "spikes"),
            Hazard(pygame.Rect(1700, 565, 90, 25), "spikes"),
            Hazard(pygame.Rect(2310, 395, 70, 24), "laser", phase=0.7),
            Hazard(pygame.Rect(2750, 425, 75, 24), "laser", phase=1.2),
            Hazard(pygame.Rect(3220, 445, 80, 24), "pulse", phase=0.3),
        ])

        # Patrol enemies are bounded to a platform-sized region.
        self.enemies.extend([
            Enemy(410, 550, 360, 490, 95 + self.number * 8),
            Enemy(920, 400, 800, 1020, 115 + self.number * 7),
            Enemy(1480, 550, 1400, 1510, 100 + self.number * 10),
            Enemy(2160, 390, 2150, 2310, 110 + self.number * 8),
            Enemy(2820, 420, 2700, 2900, 120 + self.number * 8),
            Enemy(3450, 380, 3370, 3480, 115 + self.number * 10),
        ])

        self.checkpoints = [
            Checkpoint(1450, 560),
            Checkpoint(2700, 560),
        ]
        if self.number > 1:
            # Add a little extra variation on later levels.
            self.hazards.append(Hazard(
                pygame.Rect(1850, 405, 70, 22), "pulse", phase=1.0
            ))
            self.enemies.append(Enemy(
                3050, 445, 3000, 3150, 120 + self.number * 9
            ))

    def update(self, dt: float, elapsed: float) -> None:
        for platform in self.platforms:
            platform.update(dt, elapsed)
        for coin in self.coins:
            coin.update(dt)
        for hazard in self.hazards:
            hazard.update(dt)
        for enemy in self.enemies:
            enemy.update(dt)
        for checkpoint in self.checkpoints:
            checkpoint.update(dt)
        self.portal.update(dt)

    def draw(self, surface: pygame.Surface, camera_x: float) -> None:
        for platform in self.platforms:
            platform.draw(surface, camera_x)
        for coin in self.coins:
            coin.draw(surface, camera_x)
        for hazard in self.hazards:
            hazard.draw(surface, camera_x)
        for checkpoint in self.checkpoints:
            checkpoint.draw(surface, camera_x)
        for enemy in self.enemies:
            enemy.draw(surface, camera_x)
        self.portal.draw(surface, camera_x)


# =============================================================================
# Player controller
# =============================================================================

class Player:
    """Platformer movement with coyote time, jump buffering and sprinting."""

    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y
        self.vx = 0.0
        self.vy = 0.0
        self.width = 28
        self.height = 42
        self.on_ground = False
        self.facing = 1
        self.coyote = 0.0
        self.jump_buffer = 0.0
        self.jump_held = False
        self.alive = True
        self.invulnerable = 0.0
        self.animation = 0.0
        self.landed_this_frame = False
        self.deaths = 0
        self.respawn_x = x
        self.respawn_y = y

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(round(self.x - self.width / 2),
                           round(self.y - self.height / 2),
                           self.width, self.height)

    def set_checkpoint(self, x: float, y: float) -> None:
        self.respawn_x = x
        self.respawn_y = y

    def respawn(self) -> None:
        self.x, self.y = self.respawn_x, self.respawn_y
        self.vx = self.vy = 0
        self.alive = True
        self.invulnerable = 1.4
        self.on_ground = False
        self.coyote = 0
        self.jump_buffer = 0
        self.deaths += 1

    def request_jump(self) -> None:
        self.jump_buffer = JUMP_BUFFER_TIME
        self.jump_held = True

    def release_jump(self) -> None:
        self.jump_held = False
        if self.vy < -180:
            self.vy *= 0.52

    def update(self, dt: float, keys, level: Level,
               particles: ParticleSystem) -> None:
        self.landed_this_frame = False
        self.animation += dt * (abs(self.vx) * 0.025 + 1.5)
        self.invulnerable = max(0, self.invulnerable - dt)
        self.jump_buffer = max(0, self.jump_buffer - dt)

        direction = int(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - int(
            keys[pygame.K_a] or keys[pygame.K_LEFT]
        )
        sprint = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
        max_speed = PLAYER_SPRINT_SPEED if sprint else PLAYER_MAX_SPEED
        if direction:
            self.facing = direction
            self.vx += direction * PLAYER_ACCEL * dt
            self.vx = clamp(self.vx, -max_speed, max_speed)
        else:
            friction = PLAYER_FRICTION * dt
            if abs(self.vx) <= friction:
                self.vx = 0
            else:
                self.vx -= sign(self.vx) * friction

        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            if not self.on_ground:
                self.vy += 1050 * dt

        if self.on_ground:
            self.coyote = COYOTE_TIME
        else:
            self.coyote = max(0, self.coyote - dt)

        if self.jump_buffer > 0 and (self.on_ground or self.coyote > 0):
            self.vy = -PLAYER_JUMP_SPEED
            self.on_ground = False
            self.coyote = 0
            self.jump_buffer = 0
            particles.emit(self.x, self.y + self.height / 2,
                           CYAN, count=7, speed=100, life=0.3, gravity=180)

        # Variable jump height: holding jump reduces gravity while rising.
        gravity = GRAVITY * (0.58 if self.jump_held and self.vy < 0 else 1.0)
        self.vy = min(PLAYER_MAX_FALL, self.vy + gravity * dt)

        self._move_x(dt, level.platforms)
        self._move_y(dt, level.platforms, particles)

        # Bounce pads launch the player.
        if self.on_ground:
            foot = pygame.Rect(self.rect.left + 2, self.rect.bottom - 5,
                               self.width - 4, 10)
            for platform in level.platforms:
                if platform.kind == "bounce" and foot.colliderect(platform.rect):
                    self.vy = -PLAYER_JUMP_SPEED * 1.42
                    self.on_ground = False
                    particles.emit(self.x, self.rect.bottom, GREEN, 14, 220)

    def _move_x(self, dt: float, platforms: list[Platform]) -> None:
        self.x += self.vx * dt
        rect = self.rect
        for platform in platforms:
            if rect.colliderect(platform.rect):
                if self.vx > 0:
                    rect.right = platform.rect.left
                elif self.vx < 0:
                    rect.left = platform.rect.right
                self.x = rect.centerx
                self.vx = 0
                rect = self.rect

    def _move_y(self, dt: float, platforms: list[Platform],
                particles: ParticleSystem) -> None:
        old_bottom = self.rect.bottom
        self.y += self.vy * dt
        rect = self.rect
        self.on_ground = False
        for platform in platforms:
            if not rect.colliderect(platform.rect):
                continue
            previous = platform.previous_rect or platform.rect
            # Landing only when moving down and the player's previous feet
            # were at or above the platform top.
            if self.vy >= 0 and old_bottom <= previous.top + 12:
                rect.bottom = platform.rect.top
                self.y = rect.centery
                self.vy = 0
                self.on_ground = True
                self.landed_this_frame = True
                if abs(self.vx) > 80:
                    particles.emit(self.x, rect.bottom, CYAN, 3, 45, 0.2, 80, 2)
            elif self.vy < 0:
                rect.top = platform.rect.bottom
                self.y = rect.centery
                self.vy = 0
            else:
                # Side contact while descending; prevent embedding.
                if rect.centerx < platform.rect.centerx:
                    rect.right = platform.rect.left
                else:
                    rect.left = platform.rect.right
                self.x = rect.centerx

    def draw(self, surface: pygame.Surface, camera_x: float) -> None:
        if self.invulnerable > 0 and int(self.invulnerable * 12) % 2 == 0:
            return
        r = self.rect.move(-int(camera_x), 0)
        bob = 0 if self.on_ground else int(math.sin(self.animation) * 2)
        r.y += bob
        draw_glow(surface, r.center, 33, CYAN, 35)
        # Legs animate with horizontal movement.
        leg_swing = int(math.sin(self.animation * 2) * 4) if self.on_ground else 0
        pygame.draw.line(surface, (44, 150, 184),
                         (r.centerx - 5, r.bottom - 4),
                         (r.centerx - 7 + leg_swing, r.bottom + 3), 4)
        pygame.draw.line(surface, (44, 150, 184),
                         (r.centerx + 5, r.bottom - 4),
                         (r.centerx + 7 - leg_swing, r.bottom + 3), 4)
        body = pygame.Rect(r.x + 2, r.y + 7, r.width - 4, r.height - 10)
        pygame.draw.rect(surface, (18, 83, 117), body, border_radius=7)
        pygame.draw.rect(surface, CYAN, body, 2, border_radius=7)
        # Visor points in the facing direction.
        visor = pygame.Rect(body.x + 5, body.y + 7, body.width - 10, 8)
        if self.facing < 0:
            visor.x -= 1
        pygame.draw.rect(surface, WHITE, visor, border_radius=3)
        pygame.draw.line(surface, (110, 255, 255),
                         (body.left + 4, body.bottom - 7),
                         (body.right - 4, body.bottom - 7), 2)


# =============================================================================
# UI components
# =============================================================================

class Button:
    def __init__(self, rect: pygame.Rect, label: str, action: str,
                 accent: tuple = CYAN) -> None:
        self.rect = rect
        self.label = label
        self.action = action
        self.accent = accent
        self.hovered = False

    def update(self, mouse_pos: tuple) -> None:
        self.hovered = self.rect.collidepoint(mouse_pos)

    def draw(self, surface: pygame.Surface) -> None:
        fill = (35, 52, 87) if self.hovered else (18, 29, 60)
        border = WHITE if self.hovered else self.accent
        draw_panel(surface, self.rect, fill, border, 8, 2)
        draw_text(surface, self.label, 19, WHITE if self.hovered else self.accent,
                  self.rect.centerx, self.rect.centery, center=True)

    def clicked(self, position: tuple) -> bool:
        return self.rect.collidepoint(position)


class Toast:
    """Small message panel that fades in and out."""

    def __init__(self) -> None:
        self.message = ""
        self.timer = 0.0
        self.duration = 2.0

    def show(self, message: str, duration: float = 2.0) -> None:
        self.message = message
        self.timer = duration
        self.duration = duration

    def update(self, dt: float) -> None:
        self.timer = max(0, self.timer - dt)

    def draw(self, surface: pygame.Surface) -> None:
        if self.timer <= 0:
            return
        alpha = min(1.0, (self.duration - self.timer) * 5,
                    self.timer * 2)
        width = min(520, 30 + len(self.message) * 11)
        rect = pygame.Rect((SCREEN_WIDTH - width) // 2, 88, width, 42)
        layer = pygame.Surface((width, 42), pygame.SRCALPHA)
        pygame.draw.rect(layer, (14, 25, 52, int(220 * alpha)),
                         layer.get_rect(), border_radius=10)
        pygame.draw.rect(layer, (*CYAN, int(220 * alpha)),
                         layer.get_rect(), 2, border_radius=10)
        surface.blit(layer, rect)
        draw_text(surface, self.message, 16, WHITE, rect.centerx,
                  rect.centery, center=True)


# =============================================================================
# Main game state machine
# =============================================================================

class Game:
    """Application controller: menus, level lifecycle, collisions and HUD."""

    def __init__(self) -> None:
        self.running = True
        self.state = "menu"
        self.starfield = Starfield()
        self.particles = ParticleSystem()
        self.save_data = load_save()
        self.level_number = 1
        self.level = Level(self.level_number)
        self.player = Player(*self.level.spawn)
        self.camera_x = 0.0
        self.elapsed = 0.0
        self.score = 0
        self.coins_collected = 0
        self.lives = 3
        self.level_start_score = 0
        self.debug = False
        self.ambience = True
        self.toast = Toast()
        self.buttons: list[Button] = []
        self.menu_animation = 0.0
        self.last_keys = pygame.key.get_pressed()
        self._make_menu_buttons()

    def _make_menu_buttons(self) -> None:
        self.buttons = [
            Button(pygame.Rect(SCREEN_WIDTH // 2 - 120, 335, 240, 48),
                   "START RUN", "start", CYAN),
            Button(pygame.Rect(SCREEN_WIDTH // 2 - 120, 395, 240, 48),
                   "HOW TO PLAY", "help", MAGENTA),
            Button(pygame.Rect(SCREEN_WIDTH // 2 - 120, 455, 240, 48),
                   "QUIT", "quit", RED),
        ]

    def start_game(self) -> None:
        self.level_number = 1
        self.score = 0
        self.coins_collected = 0
        self.lives = 3
        self._load_level(self.level_number)
        self.state = "playing"
        self.toast.show("SYSTEM ONLINE — GOOD LUCK")
        self.particles.emit(self.player.x, self.player.y, CYAN, 22, 220)

    def _load_level(self, number: int) -> None:
        self.level_number = number
        self.level = Level(number)
        self.player = Player(*self.level.spawn)
        self.camera_x = 0
        self.elapsed = 0
        self.level_start_score = self.score

    def restart_level(self) -> None:
        # Keep coins/score collected before entering this stage.
        self._load_level(self.level_number)
        self.toast.show("LEVEL RESTARTED")

    def next_level(self) -> None:
        self.score += 500
        self.save_data["unlocked_level"] = max(
            self.save_data.get("unlocked_level", 1), self.level_number + 1
        )
        if self.level_number >= 4:
            self.state = "victory"
            self._save_run()
            return
        self._load_level(self.level_number + 1)
        self.toast.show(f"LEVEL {self.level_number}: {self.level.name}")
        self.particles.emit(self.player.x, self.player.y, GREEN, 30, 260)

    def _save_run(self) -> None:
        self.save_data["best_score"] = max(
            self.save_data.get("best_score", 0), self.score
        )
        self.save_data["total_coins"] = (
            self.save_data.get("total_coins", 0) + self.coins_collected
        )
        save_progress(self.save_data)

    def _player_die(self, reason: str) -> None:
        if self.player.invulnerable > 0:
            return
        self.particles.emit(self.player.x, self.player.y, RED, 24, 230, 0.6)
        self.lives -= 1
        if self.lives <= 0:
            self.state = "gameover"
            self._save_run()
        else:
            self.player.respawn()
            self.toast.show(reason + " — RESPAWNING")

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self.state == "playing":
                        self.state = "paused"
                    elif self.state == "paused":
                        self.state = "playing"
                    elif self.state in ("help", "gameover", "victory"):
                        self.state = "menu"
                elif event.key == pygame.K_RETURN:
                    if self.state in ("menu", "gameover", "victory"):
                        self.start_game()
                    elif self.state == "help":
                        self.state = "menu"
                    elif self.state == "paused":
                        self.state = "playing"
                elif event.key == pygame.K_SPACE or event.key in (
                        pygame.K_w, pygame.K_UP):
                    if self.state == "playing":
                        self.player.request_jump()
                elif event.key == pygame.K_p and self.state == "playing":
                    self.state = "paused"
                elif event.key == pygame.K_r and self.state == "playing":
                    self.restart_level()
                elif event.key == pygame.K_F1:
                    self.debug = not self.debug
                elif event.key == pygame.K_m:
                    self.ambience = not self.ambience
                    self.toast.show("AMBIENCE ON" if self.ambience else "AMBIENCE OFF")
            elif event.type == pygame.KEYUP:
                if event.key in (pygame.K_SPACE, pygame.K_w, pygame.K_UP):
                    self.player.release_jump()
            elif event.type == pygame.MOUSEMOTION:
                for button in self.buttons:
                    button.update(event.pos)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.state == "menu":
                    for button in self.buttons:
                        if button.clicked(event.pos):
                            self._button_action(button.action)
                elif self.state in ("gameover", "victory"):
                    if pygame.Rect(SCREEN_WIDTH // 2 - 125, 430, 250, 50).collidepoint(event.pos):
                        self.start_game()
                    elif pygame.Rect(SCREEN_WIDTH // 2 - 125, 490, 250, 45).collidepoint(event.pos):
                        self.state = "menu"

    def _button_action(self, action: str) -> None:
        if action == "start":
            self.start_game()
        elif action == "help":
            self.state = "help"
        elif action == "quit":
            self.running = False

    def _update_playing(self, dt: float) -> None:
        self.elapsed += dt
        self.level.update(dt, self.elapsed)
        keys = pygame.key.get_pressed()
        self.player.update(dt, keys, self.level, self.particles)

        # Camera follows the player but never scrolls past the level ends.
        desired_camera = self.player.x - SCREEN_WIDTH * 0.38
        self.camera_x = lerp(self.camera_x,
                             clamp(desired_camera, 0, self.level.width - SCREEN_WIDTH),
                             min(1, dt * 5.5))

        # Collectible collision.
        player_rect = self.player.rect
        for coin in self.level.coins:
            if not coin.taken and player_rect.colliderect(
                    pygame.Rect(int(coin.x - 9), int(coin.y - 9), 18, 18)):
                coin.taken = True
                self.coins_collected += 1
                self.score += 100
                self.particles.emit(coin.x, coin.y, YELLOW, 10, 150, 0.35)
                if self.coins_collected % 5 == 0:
                    self.toast.show(f"{self.coins_collected} DATA SHARDS COLLECTED")

        # Hazards and enemies.
        for hazard in self.level.hazards:
            if hazard.active and player_rect.colliderect(hazard.rect):
                self._player_die("HAZARD CONTACT")
                break
        for enemy in self.level.enemies:
            if enemy.alive and player_rect.colliderect(enemy.rect):
                # Jumping onto an enemy defeats it; side contact costs a life.
                if self.player.vy > 120 and player_rect.bottom - enemy.rect.top < 18:
                    enemy.alive = False
                    self.player.vy = -PLAYER_JUMP_SPEED * 0.62
                    self.score += 250
                    self.particles.emit(enemy.x, enemy.y, MAGENTA, 16, 180)
                else:
                    self._player_die("DRONE HIT")
                    break

        # Checkpoints activate when touched.
        for checkpoint in self.level.checkpoints:
            checkpoint_rect = pygame.Rect(int(checkpoint.x - 16),
                                          int(checkpoint.y - 55), 32, 70)
            if not checkpoint.activated and player_rect.colliderect(checkpoint_rect):
                checkpoint.activated = True
                self.player.set_checkpoint(checkpoint.x, checkpoint.y - 45)
                self.toast.show("CHECKPOINT SAVED")
                self.particles.emit(checkpoint.x, checkpoint.y - 20, GREEN, 18, 150)

        # Falling out of the world.
        if self.player.y > SCREEN_HEIGHT + 140:
            self._player_die("FELL INTO THE VOID")

        # Portal ends the stage when the player reaches it.
        portal_rect = pygame.Rect(int(self.level.portal.x - 30),
                                  int(self.level.portal.y - 45), 60, 90)
        if player_rect.colliderect(portal_rect):
            self.next_level()

        self.particles.update(dt)
        self.toast.update(dt)

    def update(self, dt: float) -> None:
        self.menu_animation += dt
        if self.state == "playing":
            self._update_playing(dt)
        else:
            self.particles.update(dt)
            self.toast.update(dt)
            if self.state == "menu":
                self.starfield.draw(SCREEN, 0, self.menu_animation)
                self._update_menu_buttons()

    def _update_menu_buttons(self) -> None:
        mouse = pygame.mouse.get_pos()
        for button in self.buttons:
            button.update(mouse)

    def draw(self) -> None:
        if self.state == "menu":
            self._draw_menu()
        elif self.state == "help":
            self._draw_help()
        elif self.state in ("playing", "paused"):
            self._draw_game()
            if self.state == "paused":
                self._draw_pause()
        elif self.state == "gameover":
            self._draw_game()
            self._draw_end_screen(False)
        elif self.state == "victory":
            self._draw_game()
            self._draw_end_screen(True)

        if self.state not in ("menu", "help"):
            self.toast.draw(SCREEN)
        pygame.display.flip()

    def _draw_menu(self) -> None:
        self.starfield.draw(SCREEN, self.menu_animation * 22, self.menu_animation)
        # Decorative neon rings.
        cx, cy = SCREEN_WIDTH // 2, 170
        pulse = int(5 * math.sin(self.menu_animation * 2))
        draw_glow(SCREEN, (cx, cy), 110, CYAN, 28)
        pygame.draw.circle(SCREEN, (35, 90, 125), (cx, cy), 82 + pulse, 2)
        pygame.draw.circle(SCREEN, CYAN, (cx, cy), 66 + pulse, 2)
        pygame.draw.circle(SCREEN, MAGENTA, (cx, cy), 48, 1)
        draw_text(SCREEN, "N E O N", 37, WHITE, cx, cy - 8, center=True)
        draw_text(SCREEN, "R U N N E R", 18, CYAN, cx, cy + 25, center=True)
        draw_text(SCREEN, "A CYBERPUNK PLATFORM ADVENTURE", 15, MUTED,
                  cx, 270, center=True)
        for button in self.buttons:
            button.draw(SCREEN)
        draw_text(SCREEN, f"BEST SCORE  {self.save_data.get('best_score', 0):06d}",
                  15, YELLOW, cx, 535, center=True)
        draw_text(SCREEN, f"SHARDS BANKED  {self.save_data.get('total_coins', 0)}",
                  13, MUTED, cx, 560, center=True)
        draw_text(SCREEN, "PRESS ENTER TO START", 12, (78, 113, 150),
                  cx, 620, center=True)
        draw_text(SCREEN, f"v{VERSION}", 12, (68, 86, 125), 18, 15)

    def _draw_help(self) -> None:
        self.starfield.draw(SCREEN, 0, self.menu_animation)
        panel = pygame.Rect(160, 65, SCREEN_WIDTH - 320, 550)
        draw_panel(SCREEN, panel, (14, 22, 49), CYAN, 14, 2)
        draw_text(SCREEN, "FIELD MANUAL", 30, CYAN, SCREEN_WIDTH // 2, 110,
                  center=True)
        lines = [
            ("MOVE", "A / D or LEFT / RIGHT"),
            ("JUMP", "SPACE / W / UP — hold for a higher jump"),
            ("SPRINT", "LEFT SHIFT"),
            ("FAST FALL", "S / DOWN while airborne"),
            ("PAUSE", "P or ESC"),
            ("RESTART", "R"),
            ("OBJECTIVE", "Collect data shards, avoid hazards, reach the portal."),
            ("DRONES", "Jump on a drone from above to disable it."),
            ("CHECKPOINTS", "Touch a beacon to save your respawn location."),
            ("BOUNCE PADS", "Land on green pads for a boosted jump."),
        ]
        y = 165
        for heading, description in lines:
            draw_text(SCREEN, heading, 15, MAGENTA, 215, y)
            draw_text(SCREEN, description, 15, WHITE, 360, y)
            y += 38
        draw_text(SCREEN, "PRESS ENTER OR ESC TO RETURN", 14, YELLOW,
                  SCREEN_WIDTH // 2, 570, center=True)

    def _draw_game(self) -> None:
        self.starfield.draw(SCREEN, self.camera_x, self.elapsed)
        self.level.draw(SCREEN, self.camera_x)
        self.particles.draw(SCREEN, self.camera_x)
        self.player.draw(SCREEN, self.camera_x)
        self._draw_hud()
        if self.debug:
            self._draw_debug()

    def _draw_hud(self) -> None:
        # HUD backing strip
        pygame.draw.rect(SCREEN, (8, 14, 33), (0, 0, SCREEN_WIDTH, 54))
        pygame.draw.line(SCREEN, (38, 77, 110), (0, 53),
                         (SCREEN_WIDTH, 53), 2)
        draw_text(SCREEN, f"LV {self.level_number}", 18, CYAN, 20, 15)
        draw_text(SCREEN, self.level.name, 13, MUTED, 95, 19)
        draw_text(SCREEN, f"SCORE {self.score:06d}", 17, YELLOW, 430, 15)
        draw_text(SCREEN, f"SHARDS {self.coins_collected}", 15, WHITE, 620, 17)
        draw_text(SCREEN, f"LIVES {self.lives}", 15, RED, 790, 17)
        # Progress bar
        progress = clamp(self.player.x / self.level.width, 0, 1)
        pygame.draw.rect(SCREEN, (32, 43, 69), (900, 20, 170, 10),
                         border_radius=5)
        pygame.draw.rect(SCREEN, CYAN, (900, 20, int(170 * progress), 10),
                         border_radius=5)
        draw_text(SCREEN, "RUN", 10, MUTED, 900, 7)
        if self.player.invulnerable > 0:
            draw_text(SCREEN, "SHIELD", 11, GREEN, 790, 35)

    def _draw_debug(self) -> None:
        pygame.draw.rect(SCREEN, (0, 0, 0), (10, 65, 270, 92))
        draw_text(SCREEN, f"FPS: {CLOCK.get_fps():.1f}", 13, GREEN, 18, 72)
        draw_text(SCREEN, f"POS: {self.player.x:.1f}, {self.player.y:.1f}",
                  13, WHITE, 18, 92)
        draw_text(SCREEN, f"VEL: {self.player.vx:.1f}, {self.player.vy:.1f}",
                  13, WHITE, 18, 112)
        draw_text(SCREEN, f"PARTICLES: {len(self.particles.items)}",
                  13, YELLOW, 18, 132)
        # Collision boxes
        pygame.draw.rect(SCREEN, RED, self.player.rect.move(-int(self.camera_x), 0), 1)
        for platform in self.level.platforms:
            pygame.draw.rect(SCREEN, (90, 255, 150),
                             platform.rect.move(-int(self.camera_x), 0), 1)

    def _draw_pause(self) -> None:
        shade = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        shade.fill((4, 8, 22, 190))
        SCREEN.blit(shade, (0, 0))
        panel = pygame.Rect(SCREEN_WIDTH // 2 - 190, 235, 380, 210)
        draw_panel(SCREEN, panel, (15, 26, 56), CYAN, 14, 2)
        draw_text(SCREEN, "PAUSED", 34, CYAN, SCREEN_WIDTH // 2, 285, center=True)
        draw_text(SCREEN, "P / ESC / ENTER TO RESUME", 15, WHITE,
                  SCREEN_WIDTH // 2, 345, center=True)
        draw_text(SCREEN, "R TO RESTART THIS LEVEL", 13, MUTED,
                  SCREEN_WIDTH // 2, 380, center=True)

    def _draw_end_screen(self, victory: bool) -> None:
        shade = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        shade.fill((4, 7, 20, 205))
        SCREEN.blit(shade, (0, 0))
        title = "MISSION COMPLETE" if victory else "SIGNAL LOST"
        color = GREEN if victory else RED
        panel = pygame.Rect(SCREEN_WIDTH // 2 - 230, 190, 460, 360)
        draw_panel(SCREEN, panel, (14, 24, 53), color, 16, 2)
        draw_text(SCREEN, title, 31, color, SCREEN_WIDTH // 2, 245, center=True)
        draw_text(SCREEN, f"FINAL SCORE  {self.score:06d}", 20, YELLOW,
                  SCREEN_WIDTH // 2, 310, center=True)
        draw_text(SCREEN, f"DATA SHARDS  {self.coins_collected}", 16, WHITE,
                  SCREEN_WIDTH // 2, 345, center=True)
        draw_text(SCREEN, f"DRONE / HAZARD FAILURES  {self.player.deaths}",
                  14, MUTED, SCREEN_WIDTH // 2, 375, center=True)
        retry = pygame.Rect(SCREEN_WIDTH // 2 - 125, 430, 250, 50)
        menu = pygame.Rect(SCREEN_WIDTH // 2 - 125, 490, 250, 45)
        draw_panel(SCREEN, retry, (18, 42, 65), CYAN, 8)
        draw_panel(SCREEN, menu, (30, 27, 55), MAGENTA, 8)
        draw_text(SCREEN, "PLAY AGAIN", 17, CYAN, retry.centerx,
                  retry.centery, center=True)
        draw_text(SCREEN, "MAIN MENU", 15, MAGENTA, menu.centerx,
                  menu.centery, center=True)
        draw_text(SCREEN, "ENTER TO PLAY AGAIN  •  ESC FOR MENU", 11,
                  MUTED, SCREEN_WIDTH // 2, 585, center=True)

    def run(self) -> None:
        while self.running:
            # Clamp dt to avoid physics explosions after dragging the window.
            dt = min(CLOCK.tick(FPS) / 1000.0, 0.033)
            self._handle_events()
            self.update(dt)
            self.draw()
        self._save_run()
        pygame.quit()
        sys.exit(0)


# =============================================================================
# Lightweight self-checks for development
# =============================================================================

def run_self_checks() -> None:
    """Run a few pure-logic checks with: python main.py --self-test."""
    assert clamp(5, 0, 4) == 4
    assert clamp(-2, 0, 4) == 0
    assert sign(-9) == -1 and sign(0) == 0 and sign(9) == 1
    assert abs(lerp(10, 20, 0.5) - 15) < 1e-9
    assert abs(ease_out(0) - 0) < 1e-9
    assert abs(ease_out(1) - 1) < 1e-9
    level = Level(1)
    assert len(level.platforms) >= 20
    assert len(level.coins) >= 20
    assert level.portal.x > level.spawn[0]
    player = Player(100, 100)
    assert player.rect.width == player.width
    print("Self-checks passed.")


def print_startup_help() -> None:
    print("=" * 58)
    print(f"{TITLE} v{VERSION}")
    print("=" * 58)
    print("Controls: A/D or arrows move | Space jumps | Shift sprints")
    print("          S/down fast-falls | P/Esc pauses | R restarts")
    print("          F1 debug overlay | M toggles ambience indicator")
    print(f"Save file: {SAVE_FILE}")
    print("Tip: jump on drones from above to disable them.")
    print("=" * 58)


def main() -> None:
    if "--self-test" in sys.argv:
        run_self_checks()
        return
    print_startup_help()
    Game().run()


if __name__ == "__main__":
    main()
