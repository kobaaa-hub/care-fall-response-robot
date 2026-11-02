"""介護施設のフロア（廊下1本＋居室4部屋）のGazeboワールドを組み立てる。

配置（上から見た図、単位 m）:

        y=+5 ┌─────101─────┐ ┌─────102─────┐
             │  bed        │ │  bed        │      北側の部屋
        y=+1 └────┬ ┬──────┘ └────┬ ┬──────┘      入口は廊下側（y=±1）
        y= 0  ■(0,0)   ← 廊下（幅2m、x=-1〜11）     ■=待機ステーション
        y=-1 ┌────┴ ┴──────┐ ┌────┴ ┴──────┐
             │  bed        │ │  bed        │      南側の部屋
        y=-5 └─────103─────┘ └─────104─────┘
              x=1    3     5   6    8     10

各部屋は4m四方。入口の中心は 101/103 が x=3、102/104 が x=8。
部屋の中身は layer1 の1部屋ワールドと同じ（ローカル座標: 入口が -x 側、ベッドが +x 側）で、
北側の部屋はローカル +x を世界の +y に、南側はローカル +x を世界の -y に向けて置く。

単体でも動く:  python3 ward_gen.py '{"101":"in_bed","102":"standing","103":"absent","104":"fall_suspected"}' day
"""
import json
import math
import sys

SCENARIO_STATES = ("in_bed", "fall_suspected", "standing", "absent")
LIGHTINGS = ("day", "night", "night_lit")   # night_lit: 夜＋各部屋の足元灯（常夜灯）

# --- フロアの寸法 -------------------------------------------------------------
ROOMS = {  # 部屋番号: (入口中心のx, 側: +1=北, -1=南)
    "101": (3.0, +1), "102": (8.0, +1),
    "103": (3.0, -1), "104": (8.0, -1),
}
ROOM_HALF = 2.0
CORRIDOR_HALF = 1.0            # 廊下の半分の幅 → 部屋の入口壁は y=±1
CORRIDOR_X0, CORRIDOR_X1 = -1.0, 11.0
WALL_H, WALL_T = 2.4, 0.1
DOOR_HALF = 0.55
STATION = (0.0, 0.0)           # ロボットの待機位置（起動位置）
ENTRY_DEPTH = 0.6              # 入口から部屋の中へ入る距離（撮影位置）

# --- 部屋の中の寸法（ローカル座標: 入口が x=-2、ベッドが x=+1.2） ----------------------
BED_X, BED_Y = 1.2, 0.0
BED_W, BED_L = 0.95, 2.05
MATTRESS_TOP = 0.45
PERSON_LYING_HALF = 0.14
LYING_OFFSET = 0.10
# ---------------------------------------------------------------------------------


def _color(rgb):
    r, g, b = rgb
    return (f"<material><ambient>{r} {g} {b} 1</ambient><diffuse>{r} {g} {b} 1</diffuse>"
            f"<specular>0.05 0.05 0.05 1</specular></material>")


def box_w(name, x, y, z, yaw, sx, sy, sz, rgb, collide=True):
    """世界座標で箱を置く。"""
    geom = f"<geometry><box><size>{sx} {sy} {sz}</size></box></geometry>"
    col = f"<collision name='c'>{geom}</collision>" if collide else ""
    return (f"<model name='{name}'><static>true</static><pose>{x:.3f} {y:.3f} {z:.3f} 0 0 {yaw:.4f}</pose>"
            f"<link name='l'>{col}<visual name='v'>{geom}{_color(rgb)}</visual></link></model>\n")


class Room:
    """ローカル座標 → 世界座標の変換つきで部屋の中身を書く。"""

    def __init__(self, rid, door_x, side):
        self.rid = rid
        self.theta = math.pi / 2 if side > 0 else -math.pi / 2      # ローカル+x の向き
        # ローカル原点（部屋の中心）の世界座標: 入口壁(y=±1)から部屋の半分だけ奥
        self.cx = door_x
        self.cy = side * (CORRIDOR_HALF + ROOM_HALF)

    def w(self, x, y):
        c, s = math.cos(self.theta), math.sin(self.theta)
        return self.cx + x * c - y * s, self.cy + x * s + y * c

    def box(self, name, x, y, z, sx, sy, sz, rgb, collide=True):
        wx, wy = self.w(x, y)
        return box_w(f"{self.rid}_{name}", wx, wy, z, self.theta, sx, sy, sz, rgb, collide)

    def cylinder(self, name, x, y, z, r, length, rgb):
        wx, wy = self.w(x, y)
        geom = f"<geometry><cylinder><radius>{r}</radius><length>{length}</length></cylinder></geometry>"
        return (f"<model name='{self.rid}_{name}'><static>true</static><pose>{wx:.3f} {wy:.3f} {z} 0 0 0</pose>"
                f"<link name='l'><collision name='c'>{geom}</collision>"
                f"<visual name='v'>{geom}{_color(rgb)}</visual></link></model>\n")

    def person(self, x, y, z, roll=0.0, yaw=0.0):
        wx, wy = self.w(x, y)
        mesh = "<geometry><mesh><uri>model://person_standing/meshes/standing.dae</uri></mesh></geometry>"
        return (f"<model name='{self.rid}_resident'><static>true</static>"
                f"<pose>{wx:.3f} {wy:.3f} {z:.3f} {roll} 0 {self.theta + yaw:.4f}</pose>"
                f"<link name='l'><visual name='v'><pose>0 0 0.02 0.04 0 0</pose>{mesh}</visual>"
                f"<collision name='c'><pose>0 0 0.02 0.04 0 0</pose>{mesh}</collision></link></model>\n")

    def shell(self):
        h, t = ROOM_HALF, WALL_T
        wall = (0.93, 0.91, 0.86)
        s = ""
        s += self.box("floor", 0, 0, 0.005, 2 * h, 2 * h, 0.01, (0.80, 0.72, 0.58))
        s += self.box("wall_back", h, 0, WALL_H / 2, t, 2 * h, WALL_H, wall)          # ベッド側の壁
        s += self.box("wall_left", 0, h, WALL_H / 2, 2 * h, t, WALL_H, wall)
        s += self.box("wall_right", 0, -h, WALL_H / 2, 2 * h, t, WALL_H, wall)
        seg = h - DOOR_HALF                                                             # 入口の壁（廊下側）
        s += self.box("wall_front_a", -h, DOOR_HALF + seg / 2, WALL_H / 2, t, seg, WALL_H, wall)
        s += self.box("wall_front_b", -h, -DOOR_HALF - seg / 2, WALL_H / 2, t, seg, WALL_H, wall)
        s += self.box("door_lintel", -h, 0, WALL_H - 0.2, t, 2 * DOOR_HALF, 0.4, wall)
        # 部屋番号の札（入口の上、廊下側から見える）
        s += self.box("nameplate", -h - 0.06, DOOR_HALF + 0.3, 1.9, 0.02, 0.4, 0.2, (0.25, 0.35, 0.55), collide=False)
        for name, y in (("left", h - 0.06), ("right", -h + 0.06)):
            s += self.box(f"baseboard_{name}", 0, y, 0.05, 2 * h, 0.02, 0.1, (0.55, 0.47, 0.38), collide=False)
            s += self.box(f"handrail_{name}", 0, y - (0.03 if y > 0 else -0.03), 0.8, 2 * h * 0.9, 0.05, 0.05,
                          (0.62, 0.45, 0.30), collide=False)
        s += self.box("window", h - 0.06, 0, 1.45, 0.02, 1.2, 0.9, (0.70, 0.84, 0.95), collide=False)
        s += self.box("curtain_a", h - 0.09, 0.75, 1.45, 0.03, 0.3, 1.1, (0.75, 0.82, 0.68), collide=False)
        s += self.box("curtain_b", h - 0.09, -0.75, 1.45, 0.03, 0.3, 1.1, (0.75, 0.82, 0.68), collide=False)
        return s

    def bed(self, blanket_tall):
        x, y = BED_X, BED_Y
        s = ""
        s += self.box("bed_frame", x, y, 0.15, BED_W, BED_L, 0.30, (0.55, 0.57, 0.60))
        s += self.box("bed_mattress", x, y, 0.375, BED_W - 0.05, BED_L - 0.1, 0.15, (0.80, 0.88, 0.94))
        s += self.box("bed_headboard", x, y - BED_L / 2, 0.55, BED_W, 0.06, 0.9, (0.62, 0.45, 0.30))
        s += self.box("bed_footboard", x, y + BED_L / 2, 0.4, BED_W, 0.06, 0.6, (0.62, 0.45, 0.30))
        s += self.box("bed_pillow", x, y - BED_L / 2 + 0.25, MATTRESS_TOP + 0.05, 0.6, 0.3, 0.1, (1.0, 1.0, 1.0), collide=False)
        s += self.box("bed_rail", x - BED_W / 2 - 0.02, y - 0.35, MATTRESS_TOP + 0.15, 0.03, 0.8, 0.04, (0.75, 0.77, 0.80), collide=False)
        if blanket_tall:
            s += self.box("bed_blanket", x, y + 0.6, MATTRESS_TOP + 0.15, BED_W - 0.02, 0.75, 0.30, (0.55, 0.68, 0.80), collide=False)
        else:
            s += self.box("bed_blanket", x, y + 0.42, MATTRESS_TOP + 0.03, BED_W - 0.02, 1.1, 0.06, (0.62, 0.75, 0.84), collide=False)
        s += self.box("nightstand", x, y - BED_L / 2 - 0.3, 0.3, 0.45, 0.4, 0.6, (0.88, 0.84, 0.76))
        s += self.box("nurse_call", x - 0.1, y - BED_L / 2 - 0.3, 0.63, 0.08, 0.05, 0.06, (0.85, 0.35, 0.30), collide=False)
        s += self.box("chair_seat", -0.6, 1.45, 0.42, 0.45, 0.45, 0.05, (0.55, 0.45, 0.36))
        s += self.box("chair_back", -0.6, 1.66, 0.7, 0.45, 0.04, 0.55, (0.55, 0.45, 0.36))
        for i, (dx, dy) in enumerate(((-0.2, -0.2), (0.2, -0.2), (-0.2, 0.2), (0.2, 0.2))):
            s += self.cylinder(f"chair_leg{i}", -0.6 + dx, 1.45 + dy, 0.2, 0.02, 0.4, (0.40, 0.33, 0.27))
        return s

    def walker_toppled(self, x, y):
        c = (0.78, 0.80, 0.83)
        s = ""
        s += self.box("walker_a", x, y, 0.03, 0.04, 0.6, 0.04, c, collide=False)
        s += self.box("walker_b", x + 0.45, y, 0.03, 0.04, 0.6, 0.04, c, collide=False)
        s += self.box("walker_c", x + 0.22, y - 0.28, 0.03, 0.45, 0.04, 0.04, c, collide=False)
        s += self.box("walker_d", x + 0.22, y + 0.28, 0.03, 0.45, 0.04, 0.04, c, collide=False)
        return s

    def occupant(self, state):
        half_pi = 1.5708
        if state == "in_bed":
            return self.person(BED_X - 0.03, BED_Y + 1.0, MATTRESS_TOP + PERSON_LYING_HALF + LYING_OFFSET, roll=half_pi)
        if state == "fall_suspected":
            return (self.person(BED_X - 0.95, BED_Y + 0.8, PERSON_LYING_HALF + LYING_OFFSET, roll=half_pi)
                    + self.walker_toppled(BED_X - 1.6, BED_Y - 0.9))
        if state == "standing":
            return self.person(BED_X - 0.8, BED_Y + 0.5, 0.0, yaw=3.1416)
        return ""

    def build(self, state):
        return self.shell() + self.bed(blanket_tall=(state == "in_bed")) + self.occupant(state)


def corridor():
    wall = (0.93, 0.91, 0.86)
    x0, x1 = CORRIDOR_X0, CORRIDOR_X1
    L = x1 - x0
    s = ""
    s += box_w("corridor_floor", (x0 + x1) / 2, 0, 0.005, 0, L, 2 * CORRIDOR_HALF, 0.01, (0.86, 0.80, 0.68))
    # 廊下の壁のうち、部屋の入口壁が無い区間だけ埋める（x: -1..1, 5..6, 10..11）
    for (a, b) in ((x0, 1.0), (5.0, 6.0), (10.0, x1)):
        for side in (+1, -1):
            s += box_w(f"corridor_wall_{side}_{int(a*10)}", (a + b) / 2, side * CORRIDOR_HALF, WALL_H / 2, 0,
                       b - a, WALL_T, WALL_H, wall)
    # 西端は壁。東端は庭への出入口（中央に幅1.1mの開口）
    s += box_w("corridor_end_west", x0, 0, WALL_H / 2, 0, WALL_T, 2 * CORRIDOR_HALF + WALL_T, WALL_H, wall)
    seg = CORRIDOR_HALF - DOOR_HALF
    for side in (+1, -1):
        s += box_w(f"corridor_exit_{side}", x1, side * (DOOR_HALF + seg / 2), WALL_H / 2, 0, WALL_T, seg + WALL_T, WALL_H, wall)
    s += box_w("corridor_exit_lintel", x1, 0, WALL_H - 0.2, 0, WALL_T, 2 * DOOR_HALF, 0.4, wall)
    s += box_w("exit_sign", x1 - 0.06, 0, 2.05, 0, 0.02, 0.5, 0.18, (0.20, 0.60, 0.35), collide=False)
    for side in (+1, -1):  # 手すり
        s += box_w(f"corridor_rail_{side}", (x0 + x1) / 2, side * (CORRIDOR_HALF - 0.04), 0.8, 0, L - 0.2, 0.05, 0.05,
                   (0.62, 0.45, 0.30), collide=False)
    # 待機ステーション（床のマーカー）
    s += box_w("station_pad", STATION[0], STATION[1], 0.011, 0, 0.6, 0.6, 0.01, (0.55, 0.78, 0.70), collide=False)
    return s


# --- 庭（廊下の東端、x=11 の出入口の先） --------------------------------------------
GARDEN_X0, GARDEN_X1 = CORRIDOR_X1 + 0.05, 17.5
GARDEN_HALF = 4.0
GARDEN_ENTRY = (12.4, 0.0, 0.0)        # 撮影位置（小道の上、東向き）
GARDEN_APPROACH = (13.4, 0.0, 0.0)     # 駆けつけ位置
GARDEN_STATES = ("standing", "fall_suspected", "absent")
GARDEN_DITHER_DEG = (-25, 0, 25)        # 屋外は広いので振り角を大きく


def garden(state):
    g = ""
    gx = (GARDEN_X0 + GARDEN_X1) / 2
    gl = GARDEN_X1 - GARDEN_X0
    g += box_w("garden_grass", gx, 0, 0.004, 0, gl, 2 * GARDEN_HALF, 0.008, (0.38, 0.58, 0.28))
    # 小道（出入口から東へ、幅1.2m）と飛び石風のマス目
    g += box_w("garden_path", (GARDEN_X0 + 16.6) / 2, 0, 0.009, 0, 16.6 - GARDEN_X0, 1.2, 0.01, (0.70, 0.67, 0.60))
    for i in range(6):
        g += box_w(f"garden_pave_{i}", GARDEN_X0 + 0.6 + i * 0.95, 0, 0.012, 0, 0.7, 0.9, 0.005, (0.78, 0.75, 0.68), collide=False)
    # 縁石（小道の両脇。転倒の原因として見せる。ロボットが乗らないよう小道の外側に）
    for side in (+1, -1):
        g += box_w(f"garden_curb_{side}", (GARDEN_X0 + 16.6) / 2, side * 0.68, 0.04, 0, 16.6 - GARDEN_X0, 0.12, 0.08, (0.62, 0.60, 0.56), collide=False)
    # 柵（庭の外周。ロボットが出ないように）
    f = (0.55, 0.42, 0.30)
    g += box_w("garden_fence_e", GARDEN_X1, 0, 0.5, 0, 0.08, 2 * GARDEN_HALF, 1.0, f)
    g += box_w("garden_fence_n", gx, GARDEN_HALF, 0.5, 0, gl, 0.08, 1.0, f)
    g += box_w("garden_fence_s", gx, -GARDEN_HALF, 0.5, 0, gl, 0.08, 1.0, f)
    for side in (+1, -1):   # 建物側の壁（出入口の両脇）
        g += box_w(f"garden_wall_{side}", CORRIDOR_X1, side * (CORRIDOR_HALF + (GARDEN_HALF - CORRIDOR_HALF) / 2), WALL_H / 2, 0,
                   WALL_T, GARDEN_HALF - CORRIDOR_HALF, WALL_H, (0.93, 0.91, 0.86))
    # ベンチ（小道の北側）
    bx, by = 15.0, 2.0
    g += box_w("bench_seat", bx, by, 0.45, 0, 1.6, 0.5, 0.06, (0.62, 0.45, 0.30))
    g += box_w("bench_back", bx, by + 0.22, 0.75, 0, 1.6, 0.05, 0.5, (0.62, 0.45, 0.30))
    for i, dx in enumerate((-0.7, 0.7)):
        g += box_w(f"bench_leg_{i}", bx + dx, by, 0.21, 0, 0.08, 0.45, 0.42, (0.35, 0.35, 0.36))
    # 花壇（小道の南側）と木
    g += box_w("flowerbed_soil", 14.5, -2.4, 0.15, 0, 3.0, 1.2, 0.3, (0.45, 0.32, 0.22))
    for i, (dx, col) in enumerate(((-1.0, (0.90, 0.30, 0.35)), (0.0, (0.95, 0.80, 0.25)), (1.0, (0.85, 0.45, 0.70)))):
        g += box_w(f"flowers_{i}", 14.5 + dx, -2.4, 0.42, 0, 0.7, 0.8, 0.25, col, collide=False)
    g += box_w("tree_trunk", 16.6, 2.8, 0.9, 0, 0.3, 0.3, 1.8, (0.42, 0.30, 0.20))
    g += box_w("tree_crown", 16.6, 2.8, 2.5, 0, 2.0, 2.0, 1.6, (0.25, 0.50, 0.22), collide=False)
    g += box_w("tree_crown2", 16.6, 2.8, 3.3, 0.5, 1.4, 1.4, 0.8, (0.30, 0.56, 0.26), collide=False)
    g += box_w("garden_lamp_post", 13.5, 1.4, 1.2, 0, 0.08, 0.08, 2.4, (0.30, 0.30, 0.32))
    g += box_w("garden_lamp_head", 13.5, 1.4, 2.5, 0, 0.3, 0.3, 0.25, (0.95, 0.92, 0.75), collide=False)
    # 利用者
    mesh = "<geometry><mesh><uri>model://person_standing/meshes/standing.dae</uri></mesh></geometry>"

    def person(x, y, z, roll, yaw):
        return (f"<model name='garden_resident'><static>true</static><pose>{x} {y} {z} {roll} 0 {yaw}</pose>"
                f"<link name='l'><visual name='v'><pose>0 0 0.02 0.04 0 0</pose>{mesh}</visual>"
                f"<collision name='c'><pose>0 0 0.02 0.04 0 0</pose>{mesh}</collision></link></model>\n")
    if state == "fall_suspected":
        # 小道の上、縁石につまずいた体で東向きに倒れている（頭が +x）
        g += person(14.2, 0.2, PERSON_LYING_HALF + LYING_OFFSET, 1.5708, 1.5708)
        g += box_w("dropped_cane", 13.9, -0.45, 0.02, 0.3, 0.03, 0.9, 0.03, (0.35, 0.25, 0.18), collide=False)
    elif state == "standing":
        g += person(14.8, 1.2, 0.0, 0.0, -1.2)     # ベンチのそばに立って、小道のほうを向く
    return g


def lights(lighting):
    pts = [(1.5, 0), (4.5, 0), (7.5, 0), (10.5, 0)] + [(ROOMS[r][0], ROOMS[r][1] * 3.0) for r in ROOMS]
    if lighting == "night_lit":
        # 夜＋足元灯: 各部屋の入口脇の低い位置に、暖色の弱い常夜灯（介護施設の足元灯を想定）
        s = lights("night")
        for r, (dx, side) in ROOMS.items():
            s += (f"<light name='footlight_{r}' type='point'><pose>{dx + 0.9} {side * 1.3} 0.35 0 0 0</pose>"
                  "<diffuse>0.55 0.48 0.35 1</diffuse><specular>0.02 0.02 0.02 1</specular>"
                  "<attenuation><range>5</range><constant>0.5</constant><linear>0.25</linear><quadratic>0.06</quadratic></attenuation>"
                  "<cast_shadows>false</cast_shadows></light>\n")
        return s
    if lighting == "night":
        s = ("<scene><ambient>0.06 0.07 0.10 1</ambient><background>0.02 0.03 0.06 1</background>"
             "<shadows>false</shadows></scene>\n")
        for r, (dx, side) in ROOMS.items():   # 各部屋の窓から弱い月明かり
            s += (f"<light name='moon_{r}' type='spot'><pose>{dx} {side * 4.9} 1.6 0 1.2 {-math.pi/2 if side > 0 else math.pi/2}</pose>"
                  "<diffuse>0.25 0.28 0.38 1</diffuse><specular>0.05 0.05 0.05 1</specular>"
                  "<attenuation><range>6</range><constant>0.4</constant><linear>0.1</linear><quadratic>0.02</quadratic></attenuation>"
                  "<spot><inner_angle>0.6</inner_angle><outer_angle>1.2</outer_angle><falloff>1</falloff></spot>"
                  "<cast_shadows>false</cast_shadows></light>\n")
        # 廊下の常夜灯
        for i, (x, y) in enumerate(pts[:4]):
            s += (f"<light name='nightlight_{i}' type='point'><pose>{x} {y} 2.3 0 0 0</pose>"
                  "<diffuse>0.25 0.22 0.18 1</diffuse><specular>0.02 0.02 0.02 1</specular>"
                  "<attenuation><range>4</range><constant>0.7</constant><linear>0.2</linear><quadratic>0.05</quadratic></attenuation>"
                  "<cast_shadows>false</cast_shadows></light>\n")
        # 庭の外灯（小道を照らす）
        s += ("<light name='garden_lamp' type='point'><pose>13.5 1.4 2.5 0 0 0</pose>"
              "<diffuse>0.6 0.55 0.4 1</diffuse><specular>0.05 0.05 0.05 1</specular>"
              "<attenuation><range>6</range><constant>0.5</constant><linear>0.15</linear><quadratic>0.05</quadratic></attenuation>"
              "<cast_shadows>false</cast_shadows></light>\n")
        return s
    # 昼: 太陽光＋控えめな環境光だけ。天井灯を部屋ごとに置くと光が重なって真っ白になる
    s = ("<scene><ambient>0.42 0.42 0.42 1</ambient><background>0.75 0.80 0.85 1</background>"
         "<shadows>false</shadows></scene>\n<include><uri>model://sun</uri></include>\n")
    for i, (x, y) in enumerate(pts):   # 部屋と廊下に弱い補助灯（届く範囲を狭く）
        s += (f"<light name='ceiling_{i}' type='point'><pose>{x} {y} 2.3 0 0 0</pose>"
              "<diffuse>0.25 0.24 0.22 1</diffuse><specular>0.02 0.02 0.02 1</specular>"
              "<attenuation><range>3.5</range><constant>0.9</constant><linear>0.4</linear><quadratic>0.2</quadratic></attenuation>"
              "<cast_shadows>false</cast_shadows></light>\n")
    return s


def entry_pose(rid):
    """撮影位置（部屋に ENTRY_DEPTH だけ入った点）と、部屋の奥を向く向き（yaw）。"""
    if rid == "garden":
        return GARDEN_ENTRY
    door_x, side = ROOMS[rid]
    return door_x, side * (CORRIDOR_HALF + ENTRY_DEPTH), (math.pi / 2 if side > 0 else -math.pi / 2)


def approach_pose(rid):
    """駆けつけ位置（撮影位置から1mほど利用者側へ進んだ点）。"""
    if rid == "garden":
        return GARDEN_APPROACH
    door_x, side = ROOMS[rid]
    return door_x, side * (CORRIDOR_HALF + ENTRY_DEPTH + 1.0), (math.pi / 2 if side > 0 else -math.pi / 2)


def corridor_point(rid):
    """その場所の前の廊下の点（ここから入口へ向きを変えて入る）。"""
    if rid == "garden":
        return CORRIDOR_X1 - 0.6, 0.0
    return ROOMS[rid][0], 0.0


def dither(rid):
    return GARDEN_DITHER_DEG if rid == "garden" else (-15, 0, 15)


def build_world(states, lighting="day"):
    """states: {"101": "in_bed", ..., "garden": "fall_suspected"}。書かれていない場所は absent。"""
    for r, st in states.items():
        if r == "garden":
            if st not in GARDEN_STATES:
                raise ValueError(f"garden の状態は {GARDEN_STATES} のどれか: {st}")
            continue
        if r not in ROOMS:
            raise ValueError(f"部屋番号は {tuple(ROOMS)} か garden: {r}")
        if st not in SCENARIO_STATES:
            raise ValueError(f"状態は {SCENARIO_STATES} のどれか: {st}")
    if lighting not in LIGHTINGS:
        raise ValueError(f"lighting は {LIGHTINGS} のどれか: {lighting}")
    body = corridor()
    for rid, (door_x, side) in ROOMS.items():
        body += Room(rid, door_x, side).build(states.get(rid, "absent"))
    body += garden(states.get("garden", "absent"))
    return f"""<?xml version="1.0"?>
<sdf version="1.6">
<world name="care_ward">
<physics type="ode"><max_step_size>0.001</max_step_size><real_time_factor>1</real_time_factor><real_time_update_rate>1000</real_time_update_rate></physics>
<gui><camera name="user_camera"><pose>8 -11 10 0 0.85 1.5708</pose></camera></gui>
{lights(lighting)}<include><uri>model://ground_plane</uri></include>
{body}</world>
</sdf>
"""


if __name__ == "__main__":
    states = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {"101": "in_bed"}
    lt = sys.argv[2] if len(sys.argv) > 2 else "day"
    sys.stdout.write(build_world(states, lt))
