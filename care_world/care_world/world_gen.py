"""介護施設の居室（1部屋）のGazeboワールドを組み立てる。

部屋は 4m x 4m。西側の壁（x=-2）に入口があり、ロボットは入口の内側 (-1.4, 0) に
東向き（+x）で置かれる。ベッドは部屋の東寄りに南北方向（y方向）に置いてあり、
ロボットのカメラからはベッドを横から見る形になる。

scenario（利用者の状態 = 正解ラベル）:
    in_bed          ベッドで横になっている
    fall_suspected  ベッドの横の床に倒れている（歩行器が転がっている）
    standing        ベッドの横に立っている
    absent          不在
lighting:
    day    昼（太陽と天井灯）
    night  夜（消灯、窓明かりだけ）

単体でも動く:  python3 world_gen.py in_bed day > /tmp/care_room.world
"""
import sys

SCENARIOS = ("in_bed", "fall_suspected", "standing", "absent")
LIGHTINGS = ("day", "night")

# --- 寸法（見た目がおかしいときはここを調整する） --------------------------------
ROOM_HALF = 2.0                 # 部屋の半分の幅 [m]
WALL_H, WALL_T = 2.4, 0.1        # 壁の高さ・厚さ
DOOR_HALF = 0.55                 # 入口の半分の幅
BED_X, BED_Y = 1.2, 0.0          # ベッド中心
BED_W, BED_L = 0.95, 2.05        # ベッドの幅(x)・長さ(y)
MATTRESS_TOP = 0.45              # マットレス上面の高さ
PERSON_LYING_HALF = 0.14         # 横たえたときの体の厚みの半分（これだけ床やマットレスから浮かせる）
ROBOT_POSE = (-1.4, 0.0)         # ロボットの位置（launch側で使う）
# ---------------------------------------------------------------------------------


def _color(rgb):
    r, g, b = rgb
    return (f"<material><ambient>{r} {g} {b} 1</ambient><diffuse>{r} {g} {b} 1</diffuse>"
            f"<specular>0.05 0.05 0.05 1</specular></material>")


def box(name, x, y, z, sx, sy, sz, rgb, collide=True):
    """中心 (x, y, z)、大きさ (sx, sy, sz) の静止した箱。"""
    geom = f"<geometry><box><size>{sx} {sy} {sz}</size></box></geometry>"
    col = f"<collision name='c'>{geom}</collision>" if collide else ""
    return (f"<model name='{name}'><static>true</static><pose>{x} {y} {z} 0 0 0</pose>"
            f"<link name='l'>{col}<visual name='v'>{geom}{_color(rgb)}</visual></link></model>\n")


def cylinder(name, x, y, z, r, length, rgb):
    geom = f"<geometry><cylinder><radius>{r}</radius><length>{length}</length></cylinder></geometry>"
    return (f"<model name='{name}'><static>true</static><pose>{x} {y} {z} 0 0 0</pose>"
            f"<link name='l'><collision name='c'>{geom}</collision>"
            f"<visual name='v'>{geom}{_color(rgb)}</visual></link></model>\n")


def person(x, y, z, roll=0.0, pitch=0.0, yaw=0.0):
    """gazebo_models の person_standing のメッシュを、動かない（static）モデルとして置く。

    <include> だと static が効かずに物理で落ちてベッドから転がることがあったので、
    モデルを直接書く。原点は足元、頭が +z。roll=90度で頭が -y 方向に倒れる。
    """
    mesh = "<geometry><mesh><uri>model://person_standing/meshes/standing.dae</uri></mesh></geometry>"
    return (f"<model name='resident'><static>true</static><pose>{x} {y} {z} {roll} {pitch} {yaw}</pose>"
            f"<link name='l'><visual name='v'><pose>0 0 0.02 0.04 0 0</pose>{mesh}</visual>"
            f"<collision name='c'><pose>0 0 0.02 0.04 0 0</pose>{mesh}</collision></link></model>\n")


def room():
    h, t = ROOM_HALF, WALL_T
    wall = (0.93, 0.91, 0.86)
    s = ""
    s += box("floor", 0, 0, 0.005, 2 * h, 2 * h, 0.01, (0.80, 0.72, 0.58))
    s += box("wall_east", h, 0, WALL_H / 2, t, 2 * h, WALL_H, wall)
    s += box("wall_north", 0, h, WALL_H / 2, 2 * h, t, WALL_H, wall)
    s += box("wall_south", 0, -h, WALL_H / 2, 2 * h, t, WALL_H, wall)
    seg = h - DOOR_HALF
    s += box("wall_west_n", -h, DOOR_HALF + seg / 2, WALL_H / 2, t, seg, WALL_H, wall)
    s += box("wall_west_s", -h, -DOOR_HALF - seg / 2, WALL_H / 2, t, seg, WALL_H, wall)
    s += box("door_lintel", -h, 0, WALL_H - 0.2, t, 2 * DOOR_HALF, 0.4, wall)
    # 幅木と手すり（介護施設らしさ）
    for name, x, y, sx, sy in (("north", 0, h - 0.06, 2 * h, 0.02), ("south", 0, -h + 0.06, 2 * h, 0.02)):
        s += box(f"baseboard_{name}", x, y, 0.05, sx, sy, 0.1, (0.55, 0.47, 0.38), collide=False)
        s += box(f"handrail_{name}", x, y - (0.03 if y > 0 else -0.03), 0.8, sx * 0.9, 0.05, 0.05,
                 (0.62, 0.45, 0.30), collide=False)
    # 窓（東の壁、ベッドの上）とカーテン
    s += box("window", h - 0.06, 0, 1.45, 0.02, 1.2, 0.9, (0.70, 0.84, 0.95), collide=False)
    s += box("curtain_n", h - 0.09, 0.75, 1.45, 0.03, 0.3, 1.1, (0.75, 0.82, 0.68), collide=False)
    s += box("curtain_s", h - 0.09, -0.75, 1.45, 0.03, 0.3, 1.1, (0.75, 0.82, 0.68), collide=False)
    return s


def bed(blanket_tall):
    x, y = BED_X, BED_Y
    s = ""
    s += box("bed_frame", x, y, 0.15, BED_W, BED_L, 0.30, (0.55, 0.57, 0.60))
    # シーツは薄い水色（白いシャツの人物が上から見ても分かるように）
    s += box("bed_mattress", x, y, 0.375, BED_W - 0.05, BED_L - 0.1, 0.15, (0.80, 0.88, 0.94))
    s += box("bed_headboard", x, y - BED_L / 2, 0.55, BED_W, 0.06, 0.9, (0.62, 0.45, 0.30))
    s += box("bed_footboard", x, y + BED_L / 2, 0.4, BED_W, 0.06, 0.6, (0.62, 0.45, 0.30))
    s += box("bed_pillow", x, y - BED_L / 2 + 0.25, MATTRESS_TOP + 0.05, 0.6, 0.3, 0.1, (1.0, 1.0, 1.0), collide=False)
    # 手前（ロボット側）のサイドレール
    s += box("bed_rail", x - BED_W / 2 - 0.02, y - 0.35, MATTRESS_TOP + 0.15, 0.03, 0.8, 0.04, (0.75, 0.77, 0.80), collide=False)
    # 掛け布団: 人が寝ているときは脚の上だけにかけて、胴体と頭が見えるようにする
    if blanket_tall:
        s += box("bed_blanket", x, y + 0.6, MATTRESS_TOP + 0.15, BED_W - 0.02, 0.75, 0.30, (0.55, 0.68, 0.80), collide=False)
    else:
        s += box("bed_blanket", x, y + 0.42, MATTRESS_TOP + 0.03, BED_W - 0.02, 1.1, 0.06, (0.62, 0.75, 0.84), collide=False)
    # サイドテーブルとナースコール
    s += box("nightstand", x, y - BED_L / 2 - 0.3, 0.3, 0.45, 0.4, 0.6, (0.88, 0.84, 0.76))
    s += box("nurse_call", x - 0.1, y - BED_L / 2 - 0.3, 0.63, 0.08, 0.05, 0.06, (0.85, 0.35, 0.30), collide=False)
    # 部屋の手前の椅子
    s += box("chair_seat", -0.6, 1.45, 0.42, 0.45, 0.45, 0.05, (0.55, 0.45, 0.36))
    s += box("chair_back", -0.6, 1.66, 0.7, 0.45, 0.04, 0.55, (0.55, 0.45, 0.36))
    for i, (dx, dy) in enumerate(((-0.2, -0.2), (0.2, -0.2), (-0.2, 0.2), (0.2, 0.2))):
        s += cylinder(f"chair_leg{i}", -0.6 + dx, 1.45 + dy, 0.2, 0.02, 0.4, (0.40, 0.33, 0.27))
    return s


def walker_toppled(x, y):
    """床に倒れた歩行器（フレームだけ）。"""
    c = (0.78, 0.80, 0.83)
    s = ""
    s += box("walker_a", x, y, 0.03, 0.04, 0.6, 0.04, c, collide=False)
    s += box("walker_b", x + 0.45, y, 0.03, 0.04, 0.6, 0.04, c, collide=False)
    s += box("walker_c", x + 0.22, y - 0.28, 0.03, 0.45, 0.04, 0.04, c, collide=False)
    s += box("walker_d", x + 0.22, y + 0.28, 0.03, 0.45, 0.04, 0.04, c, collide=False)
    return s


def occupant(scenario):
    """利用者の人物モデルと、状態に合わせた小物。"""
    half_pi = 1.5708
    # 人物メッシュは体の厚み（前後）が原点から -y 側に約0.1ずれているので、
    # roll=90度で倒すと体の中心が原点より約0.1低くなる。その分を足して置く。
    lying_offset = 0.10
    if scenario == "in_bed":
        # 仰向けに寝かせる: roll=90度で頭が -y（枕側）。足元の原点を足板の少し手前に置く
        return person(BED_X - 0.03, BED_Y + 1.0, MATTRESS_TOP + PERSON_LYING_HALF + lying_offset, roll=half_pi)
    if scenario == "fall_suspected":
        # ベッドの手前（ロボット側）の床に倒れている
        return (person(BED_X - 0.95, BED_Y + 0.8, PERSON_LYING_HALF + lying_offset, roll=half_pi)
                + walker_toppled(BED_X - 1.6, BED_Y - 0.9))
    if scenario == "standing":
        # ベッドの手前に立っている（ロボットの方を向かせる）
        return person(BED_X - 0.8, BED_Y + 0.5, 0.0, yaw=3.1416)
    return ""  # absent


def lights(lighting):
    if lighting == "night":
        return ("<scene><ambient>0.06 0.07 0.10 1</ambient><background>0.02 0.03 0.06 1</background>"
                "<shadows>false</shadows></scene>\n"
                # 窓から入る弱い月明かり
                "<light name='moonlight' type='spot'><pose>1.9 0 1.6 0 1.2 3.1416</pose>"
                "<diffuse>0.25 0.28 0.38 1</diffuse><specular>0.05 0.05 0.05 1</specular>"
                "<attenuation><range>6</range><constant>0.4</constant><linear>0.1</linear><quadratic>0.02</quadratic></attenuation>"
                "<spot><inner_angle>0.6</inner_angle><outer_angle>1.2</outer_angle><falloff>1</falloff></spot>"
                "<cast_shadows>false</cast_shadows></light>\n")
    return ("<scene><ambient>0.55 0.55 0.55 1</ambient><background>0.75 0.80 0.85 1</background>"
            "<shadows>false</shadows></scene>\n"
            "<include><uri>model://sun</uri></include>\n"
            "<light name='ceiling' type='point'><pose>0 0 2.3 0 0 0</pose>"
            "<diffuse>0.9 0.88 0.82 1</diffuse><specular>0.1 0.1 0.1 1</specular>"
            "<attenuation><range>8</range><constant>0.6</constant><linear>0.05</linear><quadratic>0.01</quadratic></attenuation>"
            "<cast_shadows>false</cast_shadows></light>\n")


def build_world(scenario="in_bed", lighting="day"):
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario は {SCENARIOS} のどれか: {scenario}")
    if lighting not in LIGHTINGS:
        raise ValueError(f"lighting は {LIGHTINGS} のどれか: {lighting}")
    return f"""<?xml version="1.0"?>
<sdf version="1.6">
<world name="care_room">
<physics type="ode"><max_step_size>0.001</max_step_size><real_time_factor>1</real_time_factor><real_time_update_rate>1000</real_time_update_rate></physics>
<gui><camera name="user_camera"><pose>-3.2 -3.2 4.2 0 0.75 0.785</pose></camera></gui>
{lights(lighting)}<include><uri>model://ground_plane</uri></include>
{room()}{bed(blanket_tall=(scenario == "in_bed"))}{occupant(scenario)}</world>
</sdf>
"""


if __name__ == "__main__":
    sc = sys.argv[1] if len(sys.argv) > 1 else "in_bed"
    lt = sys.argv[2] if len(sys.argv) > 2 else "day"
    sys.stdout.write(build_world(sc, lt))
