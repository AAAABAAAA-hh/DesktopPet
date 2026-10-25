"""Procedural placeholder character art for Deskling.

Only the base character (body, head, articulated parts) is drawn here.  Every
layer is exported on the same 360 x 540 transparent design canvas so a body
and its expressions stay aligned.  Wardrobe, food and prop art is **not**
produced by code any more: those are standalone PNG sprites mounted through
``assets/items/catalog.json`` and each character's ``mount_points``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PIL import Image

from artkit import (
    CREAM,
    INK,
    MOUTH,
    OUTLINE,
    TONGUE,
    Art,
    bezier,
    canvas,
    save_layer,
)

CharDict = dict


PROFILES: list[CharDict] = [
    {
        "slug": "azhai",
        "name": "阿宅",
        "subtitle": "后排摸鱼冠军",
        "order": 1,
        "scale": 0.88,
        "temper": 1.15,
        "accent": "#7B68EE",
        "accent2": "#FFD166",
        "style": "messy",
        "glasses": False,
        "hair": "#3E3457",
        "hair_hi": "#655584",
        "eye": "#6B5585",
        "skin": "#FFD8C0",
        "blush": "#FFA8A2",
        "top": "#8B79F2",
        "top_dark": "#6654D8",
        "bottom": "#44405E",
        "shoe": "#F7EFE2",
        "sole": "#6A5F78",
        "sock": "#FCF8F0",
        "symbol": "#FFD166",
        "lines": {
            "poke": [
                "喂喂喂，代码可以乱，脸不能乱戳！",
                "再戳我就把你的 bug 全塞回去。",
                "你点我干嘛？我脸上有 IDE 吗？",
                "别戳了，我刚刚才把头发捋顺。",
                "嘶——你当我是回车键啊？",
            ],
            "pat": [
                "唔……再摸一下也不是不行。",
                "这不是摸头，这是精神损失费。",
                "手法还行，给你打八分。",
                "呼噜……谁、谁打呼噜了？",
            ],
            "body": [
                "喂，摸哪儿呢？我这纸片身子会起皱的。",
                "别戳肚子，那里面全是外卖。",
                "你手放尊重点，我可是有尊严的宅。",
            ],
            "anger": [
                "火气上来了啊，我警告你。",
                "再点一下，我就把键盘塞你脸上。",
                "我忍你很久了，别逼我开机。",
            ],
            "drag": [
                "啊啊啊我恐高！放我下来！",
                "你拎猫呢？我是纸片人，会飘的！",
                "救命——室友谋杀案现场！",
            ],
            "drop": [
                "哎哟！我的纸片腰！",
                "你完了，我已经记在小本本上了。",
                "地板挺凉快，谢谢你了。",
            ],
            "feed": [
                "这鸡腿……有点东西。",
                "谢谢室友，再来一份。",
                "我先声明，这不是我主动要吃的。",
            ],
            "spit": [
                "呸！这玩意儿也能叫饭？",
                "你喂我吃垃圾文件？良心呢？",
                "这个卡路里不对，退货。",
            ],
            "sleep": [
                "别吵，我在梦里写代码……",
                "晚安，bug 留给明天的我。",
                "敢弄醒我，后果自负。",
            ],
            "wake": [
                "嗯？开饭了吗？",
                "我梦见自己成了大佬，然后你把我戳醒了。",
            ],
            "rage": [
                "你成功惹毛了一个有键盘的纸片人！",
                "今天不是你死就是你电脑死！",
                "鼠标借我用三秒！",
            ],
            "work": [
                "又在卷？键盘都快冒烟了。",
                "写吧写吧，我负责在旁边监工。",
                "IDE 开了这么久，bug 修完了吗？",
            ],
            "play": [
                "又在摸鱼？带我一个！",
                "说好的学习呢？我截图了啊。",
                "好好好，游戏比我重要是吧。",
            ],
            "idle": [
                "人生真是寂寞如雪。",
                "今天也是不想写代码的一天。",
                "我听见你鼠标在抖。",
                "要不，去食堂？",
            ],
            "hungry": ["肚子在抗议了，投喂一下？", "饭！饭！饭！"],
            "study": ["行吧，陪你学一会儿。", "学霸模式启动，虽然只管五分钟。"],
        },
        "voice_pitch": 1.0,
    },
    {
        "slug": "xiaoman",
        "name": "小满",
        "subtitle": "宿舍气氛组组长",
        "order": 2,
        "scale": 0.84,
        "temper": 0.75,
        "accent": "#FF8A5B",
        "accent2": "#55BFA9",
        "style": "buns",
        "glasses": False,
        "hair": "#D37D66",
        "hair_hi": "#F2A88D",
        "eye": "#7F4B3D",
        "skin": "#FFDDC7",
        "blush": "#FF9B9B",
        "top": "#FF9E63",
        "top_dark": "#E2763D",
        "bottom": "#4E688F",
        "shoe": "#FFF4D9",
        "sole": "#6A5F78",
        "sock": "#FFFFFF",
        "symbol": "#55BFA9",
        "lines": {
            "poke": [
                "哎呀！戳我脸会被可爱反噬的！",
                "再戳，我就把你的论文排版弄乱！",
                "嘿嘿，你是不是想跟我玩？",
                "痛诶！我这可是限量版脸蛋！",
            ],
            "pat": [
                "嘿嘿嘿，舒服，继续继续！",
                "摸头点赞一条龙，谢谢老板！",
                "好家伙，手法比食堂阿姨还稳。",
            ],
            "body": [
                "嘿嘿，是不是想抱我？",
                "摸我一下要收一颗糖哦。",
                "别闹别闹，痒！",
            ],
            "anger": [
                "我可爱归可爱，但也是有脾气的！",
                "再戳我要喊人了啊！",
                "气鼓鼓模式启动！哼！",
            ],
            "drag": [
                "飞咯！我是宿舍风筝！",
                "哇——下面的人让一让！",
                "放我下来，我还没系安全带！",
            ],
            "drop": [
                "着陆成功！满分十分！",
                "哎哟，屁股着地，扣两分。",
                "地板：怎么又是你。",
            ],
            "feed": [
                "哇！好香！你怎么知道我爱吃！",
                "谢谢你，我宣布你是我最好的室友！",
                "干饭人，干饭魂！",
            ],
            "spit": [
                "呸呸呸，这是啥黑暗料理！",
                "你是不是想毒害气氛组组长？",
                "不吃不吃，拿开拿开！",
            ],
            "sleep": [
                "我先眯一会儿，有瓜记得叫我。",
                "晚安！梦里不许卷！",
                "别偷看我睡觉，我会害羞的。",
            ],
            "wake": [
                "到饭点了？我就知道！",
                "啊？我刚刚没睡，我在闭目养神。",
            ],
            "rage": [
                "我的可爱是有限度的！超限了！",
                "你完了！我要召唤全宿舍围观你！",
                "看我今天不把你鼠标没收！",
            ],
            "work": [
                "哇，你居然真的在学！我有点不习惯。",
                "冲鸭！学完这页我们去买奶茶！",
                "今天的你有点帅哦，认真脸认证。",
            ],
            "play": [
                "摸鱼被我发现啦！分我一半！",
                "别只顾着玩，也看看我嘛。",
                "好耶，摸鱼！我是同谋！",
            ],
            "idle": [
                "今天我们玩点什么？",
                "我刚刚看到你桌面有个文件在动。",
                "唱歌吗？我只会跑调的那种。",
            ],
            "hungry": ["肚子咕咕叫，我听见了！", "投喂！投喂！投喂！"],
            "study": ["陪你学习！三分钟热度也是热度！", "冲鸭，学它！"],
        },
        "voice_pitch": 1.25,
    },
    {
        "slug": "laowang",
        "name": "老王",
        "subtitle": "宿舍卷王兼养生大师",
        "order": 3,
        "scale": 0.9,
        "temper": 0.6,
        "accent": "#7F9E62",
        "accent2": "#E8C65A",
        "style": "short",
        "glasses": False,
        "hair": "#384C43",
        "hair_hi": "#5E7969",
        "eye": "#4E3D31",
        "skin": "#F2C6A4",
        "blush": "#E89C91",
        "top": "#7D9B66",
        "top_dark": "#5E7B4B",
        "bottom": "#3B3A38",
        "shoe": "#E6DED0",
        "sole": "#4C4A45",
        "sock": "#EDE7D9",
        "symbol": "#E8C65A",
        "lines": {
            "poke": [
                "小同志，戳人是不礼貌的。",
                "你这手啊，太闲了，去做两道题。",
                "我劝你善良，也劝你早睡。",
                "再戳，我就给你讲高数。",
            ],
            "pat": [
                "嗯，稳。",
                "行了行了，摸两下得了。",
                "按摩可以，办卡免谈。",
            ],
            "body": [
                "小同志，动手动脚的不合适。",
                "这属于非必要身体接触。",
                "摸吧摸吧，反正也是纸。",
            ],
            "anger": [
                "血压上来了，你负责。",
                "年轻人，你这是要挨批评的。",
                "我这就去写举报信。",
            ],
            "drag": [
                "这不符合力学。",
                "放我下来，我的泡脚水要凉了。",
                "年轻人，不要搞这种危险动作。",
            ],
            "drop": [
                "地心引力，诚不欺我。",
                "下次轻点，我这把老骨头。",
                "没事，正好活动活动。",
            ],
            "feed": [
                "嗯，营养均衡，不错。",
                "吃饭不积极，思想有问题。",
                "谢谢，不过下次少放辣。",
            ],
            "spit": [
                "这东西，吃了折寿。",
                "我建议你把它拖进回收站。",
                "不了不了，你还是自己留着吧。",
            ],
            "sleep": [
                "养生时间，闲人勿扰。",
                "早睡早起，方能长寿。",
                "我要开始打坐了，呼……",
            ],
            "wake": [
                "几点了？我是不是错过早课了？",
                "睡醒一觉，精神百倍。",
            ],
            "rage": [
                "忍无可忍，无需再忍。",
                "看来今天要替你室友教育教育你。",
                "把我的保温杯拿来，我要认真了。",
            ],
            "work": [
                "不错，年轻人就该多学习。",
                "这个知识点，我建议你再看一遍。",
                "稳住，写完这段就休息一下。",
            ],
            "play": [
                "适度娱乐，不要沉迷。",
                "玩了多久了？眼睛要不要了？",
                "行吧，就一局，我计时。",
            ],
            "idle": [
                "今天喝八杯水了吗？",
                "久坐伤腰，起来走两步。",
                "这桌面，挺有生活气息。",
            ],
            "hungry": ["到饭点了，食堂见。", "人是铁饭是钢。"],
            "study": ["好，我们一起把这块硬骨头啃了。", "学习使我快乐，真的。"],
        },
        "voice_pitch": 0.78,
    },
    {
        "slug": "linlin",
        "name": "林林",
        "subtitle": "图书馆常驻 NPC",
        "order": 4,
        "scale": 0.82,
        "temper": 0.9,
        "accent": "#7FA8C9",
        "accent2": "#F08FA3",
        "style": "long",
        "glasses": True,
        "hair": "#323047",
        "hair_hi": "#5B5878",
        "eye": "#514665",
        "skin": "#FFDCC7",
        "blush": "#F6A6A8",
        "top": "#91B5D2",
        "top_dark": "#668CAA",
        "bottom": "#4C5B73",
        "shoe": "#F1E9E4",
        "sole": "#5C5567",
        "sock": "#FFFFFF",
        "symbol": "#F08FA3",
        "lines": {
            "poke": [
                "……你打扰到我看书了。",
                "再戳一次，我就把你的借阅记录念出来。",
                "这是学术骚扰。",
                "我在思考，你却在戳我。",
            ],
            "pat": [
                "嗯……这页看完再说。",
                "情绪价值已收到，请继续。",
                "安静地摸摸，就很好。",
            ],
            "body": [
                "……请不要打扰我看书。",
                "手拿开，这页还没看完。",
                "碰我可以，别碰我的书。",
            ],
            "anger": [
                "我已经在忍了，请不要让我开口。",
                "这属于噪音污染。",
                "再戳我就把你写进观察日记。",
            ],
            "drag": [
                "书！我的书要掉了！",
                "请放我回地面，谢谢配合。",
                "我恐高，这不科学。",
            ],
            "drop": [
                "……我假装什么都没发生。",
                "书页散了，你赔。",
                "落地姿势还可以。",
            ],
            "feed": [
                "谢谢，正好看饿了。",
                "边看书边吃，效率翻倍。",
                "这家味道不错，下次还点。",
            ],
            "spit": [
                "这个不能吃，谢谢。",
                "我建议你先读一遍说明书。",
                "拿走，我的书都比它好吃。",
            ],
            "sleep": [
                "让我在知识的海洋里睡一会儿。",
                "晚安，明天早八……当我没说。",
                "书盖在脸上，谁都别叫我。",
            ],
            "wake": [
                "几点了？我是不是又睡着了？",
                "嗯……刚刚梦到一个很妙的点子。",
            ],
            "rage": [
                "我的安静是有限度的。",
                "请把我的耳机还给我。",
                "今天破例，不学习了，先教育你。",
            ],
            "work": [
                "专注的样子，很好。",
                "这一段写得不错，继续。",
                "图书馆的座位我帮你占了。",
            ],
            "play": [
                "……你刚刚不是说要学习吗？",
                "好吧，放松也很重要。",
                "我假装没看见你在摸鱼。",
            ],
            "idle": [
                "今天的借阅额度还剩三本。",
                "你桌面太乱了，需要整理。",
                "安静，是一种美德。",
            ],
            "hungry": ["肚子有点饿，但是书还没看完。", "先去吃饭吧。"],
            "study": ["那就一起安静地学吧。", "这次我把手机收起来。"],
        },
        "voice_pitch": 1.1,
    },
    {
        "slug": "elaina",
        "name": "伊蕾娜",
        "subtitle": "灰之魔女 · 旅行中",
        "order": 5,
        "scale": 0.88,
        "temper": 0.9,
        "accent": "#9B7BD6",
        "accent2": "#E8C65A",
        "style": "long",
        "glasses": False,
        "hair": "#D8D0EC",
        "hair_hi": "#FBF8FF",
        "eye": "#8B6FAE",
        "skin": "#FFE0CC",
        "blush": "#F2A8B8",
        "top": "#383244",
        "top_dark": "#24202E",
        "bottom": "#4A3B5C",
        "shoe": "#F2ECF7",
        "sole": "#3B3340",
        "sock": "#FFFFFF",
        "symbol": "#E8C65A",
        # The hat is painted into the art, so no wardrobe hat is needed.
        "starting_accessories": [],
        "lines": {
            "poke": [
                "别戳了，我正在整理旅行笔记。",
                "再戳，我就把你写进我的游记。",
                "这位同学，你的手是不是太闲了？",
                "魔女的脸也是脸，会痛的。",
            ],
            "pat": [
                "嗯……这算旅途中的小费吗？",
                "手法不错，允许你再摸两下。",
                "别得寸进尺，我只是刚好心情好。",
            ],
            "body": [
                "请不要随便碰魔女的袍子。",
                "这身可是旅行限定款。",
                "再摸，我就把你变成青蛙。",
            ],
            "anger": [
                "我的耐心也是有限的。",
                "你最好现在就停手。",
                "看来有人想尝尝魔法。",
            ],
            "drag": [
                "喂——我还没系好扫帚！",
                "放我下来，我自己会飞。",
                "这就是你们的待客之道吗？",
            ],
            "drop": [
                "落地姿势，勉强及格。",
                "我的帽子差点飞了。",
                "下次请温柔一点。",
            ],
            "feed": [
                "旅行途中能吃到热饭，不错。",
                "谢谢，我会记得这顿的。",
                "味道可以，给你加一分。",
            ],
            "spit": [
                "这东西……你确定能吃？",
                "请不要拿魔法实验品喂我。",
                "我拒绝，退货。",
            ],
            "sleep": [
                "晚安，明天还要赶路。",
                "别吵，我在梦里环游世界。",
                "帽子帮我放好。",
            ],
            "wake": [
                "天亮了吗？",
                "我刚刚梦见一片很漂亮的海。",
            ],
            "rage": [
                "你成功惹恼了一位魔女。",
                "今天，就让你见识一下灰之魔女的厉害。",
                "我的扫帚呢？",
            ],
            "work": [
                "又在卷？旅途也要注意休息。",
                "写完这段，就去看一眼窗外吧。",
                "专注的样子，还不错。",
            ],
            "play": [
                "摸鱼被我发现了。",
                "休息一下也好，我陪你。",
                "别玩太久，眼睛会累的。",
            ],
            "idle": [
                "下一站，去哪里好呢？",
                "这桌面，比旅馆的床还干净。",
                "旅行笔记又写完一本了。",
                "你见过会飞的纸片人吗？",
            ],
            "hungry": ["肚子饿了，附近有面包店吗？", "旅费可以省，饭不能省。"],
            "study": ["那就一起安静地看会儿书吧。", "知识也是旅行的行李。"],
        },
        "voice_pitch": 1.15,
    },
]


# ---------------------------------------------------------------------------
# body
# ---------------------------------------------------------------------------


def _shoe(art: Art, cx: float, cy: float, flip: int, colour: str, sole: str) -> None:
    """A chunky little sneaker centred around the ankle point."""

    box = (cx - 30, cy - 16, cx + 30 + flip * 7, cy + 17)
    art.ellipse(box, colour, width=3.2)
    art.line([(box[0] + 8, box[3] - 5), (box[2] - 8, box[3] - 5)], sole, 4.5)
    art.line([(cx - 12, cy - 8), (cx + 3, cy - 8)], (255, 255, 255, 130), 3.0)


def _arm(
    art: Art,
    points: Sequence[tuple[float, float]],
    profile: CharDict,
    cuff: bool = True,
) -> None:
    shoulder, elbow, wrist = points[0], points[-2], points[-1]
    sleeve = profile["top"]
    # upper sleeve
    art.limb([shoulder, elbow], 34, sleeve, 3.4)
    if cuff:
        art.circle(elbow[0], elbow[1], 17, profile["top_dark"], width=2.5)
    # forearm
    art.limb([elbow, wrist], 21, profile["skin"], 3.2)
    art.circle(wrist[0], wrist[1], 14, profile["skin"], width=3.0)
    # tiny thumb
    art.circle(wrist[0] + (8 if wrist[0] > 180 else -8), wrist[1] - 3, 6, profile["skin"], width=2.0)


def _leg(
    art: Art,
    hip: tuple[float, float],
    knee: tuple[float, float],
    ankle: tuple[float, float],
    profile: CharDict,
    flip: int,
) -> None:
    art.limb([hip, knee, ankle], 26, profile["skin"], 3.2)
    # sock
    art.line([(ankle[0] - 11, ankle[1] - 5), (ankle[0] + 11, ankle[1] - 5)], profile["sock"], 8)
    _shoe(art, ankle[0], ankle[1] + 5, flip, profile["shoe"], profile["sole"])


#: Rig layer names.  Every part is drawn on the same 360x540 canvas, so at
#: runtime each one only needs to be rotated around its own joint pivot.
RIG_PARTS = ("leg_left", "leg_right", "arm_left", "arm_right", "torso")

#: Joint pivots in design-space fractions of the canvas.  They sit *inside*
#: the torso / shorts silhouette, so rotating a limb never opens a seam.
RIG_PIVOTS = {
    "torso": (0.5, 0.775),
    "arm_left": (0.3333, 0.5481),
    "arm_right": (0.6667, 0.5481),
    "leg_left": (0.4194, 0.7778),
    "leg_right": (0.5806, 0.7778),
    "head": (0.5, 0.4556),
}


def _body_geometry(pose: str) -> dict[str, tuple[tuple[float, float], ...]]:
    """Joint chains per limb for each legacy body pose."""

    if pose == "walk":
        left = ((150, 420), (121, 468), (104, 502))
        right = ((210, 420), (238, 470), (256, 502))
        left_arm = ((121, 296), (95, 350), (103, 396))
        right_arm = ((239, 296), (264, 342), (255, 386))
    elif pose == "dangle":
        left = ((151, 422), (115, 470), (92, 504))
        right = ((209, 422), (249, 458), (279, 489))
        left_arm = ((120, 296), (91, 266), (72, 240))
        right_arm = ((240, 296), (269, 266), (288, 240))
    else:
        left = ((151, 420), (146, 477), (136, 503))
        right = ((209, 420), (214, 477), (224, 503))
        left_arm = ((120, 296), (92, 346), (88, 391))
        right_arm = ((240, 296), (268, 346), (272, 391))
    return {
        "leg_left": left,
        "leg_right": right,
        "arm_left": left_arm,
        "arm_right": right_arm,
    }


def _draw_torso(art: Art, profile: CharDict) -> None:
    """Neck, shorts, shirt and badges: everything that is not a limb."""

    skin = profile["skin"]
    top = profile["top"]
    top_dark = profile["top_dark"]
    bottom = profile["bottom"]

    # neck (behind head and collar)
    art.rounded((157, 218, 203, 302), 18, skin, width=3.2)
    art.line([(166, 244), (194, 244)], (0, 0, 0, 20), 2)

    # shorts / trousers
    art.rounded((106, 384, 254, 456), 30, bottom, width=3.4)
    art.line([(180, 414), (180, 450)], (44, 38, 52, 110), 3.2)
    art.line([(120, 404), (166, 404)], (255, 255, 255, 45), 4)
    # little hem highlight
    art.line([(122, 448), (238, 448)], (0, 0, 0, 35), 2.2)

    # torso
    art.rounded((103, 274, 257, 414), 34, top, width=3.6)
    # neckline
    art.ellipse((151, 266, 209, 302), skin, width=3.0)
    art.line([(154, 290), (206, 290)], (0, 0, 0, 30), 2.0)
    # hem
    art.line([(117, 397), (243, 397)], top_dark, 4.2)
    art.line([(134, 401), (226, 401)], (255, 255, 255, 45), 2.5)

    if profile["slug"] == "azhai":
        # hood strings and kangaroo pocket
        art.line([(166, 286), (165, 329)], top_dark, 3.2)
        art.line([(194, 286), (195, 329)], top_dark, 3.2)
        art.circle(165, 331, 3.6, profile["accent2"], width=1.6)
        art.circle(195, 331, 3.6, profile["accent2"], width=1.6)
        art.rounded((135, 355, 225, 390), 12, top_dark, width=2.6)
        art.line([(143, 364), (217, 364)], (255, 255, 255, 35), 2.5)
    elif profile["slug"] == "xiaoman":
        art.line([(103, 327), (225, 327)], top_dark, 3.0)
        art.ellipse((110, 276, 145, 311), profile["top_dark"], width=2.0)
        art.ellipse((215, 276, 250, 311), profile["top_dark"], width=2.0)
    elif profile["slug"] == "laowang":
        art.polygon([(149, 275), (180, 310), (211, 275)], CREAM, width=3.0)
        art.line([(172, 301), (175, 330)], top_dark, 2.6)
        art.circle(174, 338, 3.2, profile["accent2"], width=1.4)
        art.line([(127, 328), (233, 328)], (0, 0, 0, 30), 2.0)
    elif profile["slug"] == "elaina":
        # travelling witch: white collar, gold clasp, flowing robe trim
        art.polygon([(149, 275), (180, 318), (211, 275)], CREAM, width=2.6)
        art.line([(180, 318), (180, 359)], top_dark, 2.4)
        art.circle(180, 330, 8.0, profile["accent2"], width=2.0)
        art.circle(180, 330, 3.2, profile["accent"], width=1.2)
        art.line([(123, 390), (237, 390)], profile["accent2"], 2.8)
        art.line([(130, 397), (230, 397)], (255, 255, 255, 38), 2.0)
    else:
        # cardigan
        art.polygon([(103, 278), (151, 278), (141, 397), (103, 397)], top)
        art.polygon([(257, 278), (209, 278), (219, 397), (257, 397)], top)
        art.polygon([(151, 278), (209, 278), (197, 390), (163, 390)], CREAM, width=2.6)
        art.line([(155, 300), (151, 381)], top_dark, 2.4)
        art.circle(153, 343, 4.5, profile["accent2"], width=1.5)
        art.circle(154, 357, 4.5, profile["accent2"], width=1.5)

    # chest emblem
    symbol = profile["symbol"]
    if profile["symbol"] == "#FFD166" and profile["slug"] == "azhai":
        art.star(180, 333, 20, symbol, OUTLINE, points=4)
    elif profile["slug"] == "xiaoman":
        art.star(180, 350, 19, symbol, OUTLINE, points=5)
    elif profile["slug"] == "laowang":
        art.polygon(
            [(180, 338), (197, 348), (193, 368), (180, 376), (167, 368), (163, 348)],
            symbol,
            OUTLINE,
            2.2,
        )
        art.line([(180, 347), (180, 367)], OUTLINE, 2.0)
    elif profile["slug"] == "elaina":
        art.star(180, 351, 18, symbol, OUTLINE, points=5)
    else:
        art.heart(180, 351, 25, symbol)

    # collar / clothes final touches over neckline
    if profile["slug"] == "laowang":
        art.polygon([(149, 275), (180, 310), (211, 275)], CREAM, width=3.0)


def build_body_parts(profile: CharDict, pose: str = "idle") -> dict[str, Image.Image]:
    """Render the character as five independent, pivotable layers."""

    parts = {name: canvas() for name in RIG_PARTS}
    geometry = _body_geometry(pose)
    _leg(Art(parts["leg_left"]), *geometry["leg_left"], profile, flip=-1)
    _leg(Art(parts["leg_right"]), *geometry["leg_right"], profile, flip=1)
    _arm(Art(parts["arm_left"]), geometry["arm_left"], profile)
    _arm(Art(parts["arm_right"]), geometry["arm_right"], profile)
    _draw_torso(Art(parts["torso"]), profile)
    return parts


def build_body(profile: CharDict, pose: str = "idle") -> Image.Image:
    """Composite the rig parts back into the classic single body layer."""

    parts = build_body_parts(profile, pose)
    img = canvas()
    for name in RIG_PARTS:
        img.alpha_composite(parts[name])
    return img


# ---------------------------------------------------------------------------
# head
# ---------------------------------------------------------------------------


def _back_hair(art: Art, p: CharDict) -> None:
    hair = p["hair"]
    hi = p["hair_hi"]
    style = p["style"]
    if style == "messy":
        art.ellipse((51, 25, 309, 259), hair, width=3.8)
        art.polygon([(61, 116), (33, 153), (43, 184), (65, 171)], hair, width=3.2)
        art.polygon([(299, 113), (329, 148), (321, 183), (294, 167)], hair, width=3.2)
        art.polygon([(236, 43), (271, 20), (266, 47)], hair, width=2.4)
    elif style == "buns":
        art.ellipse((55, 30, 305, 246), hair, width=3.8)
        # side flips
        art.polygon([(60, 133), (33, 197), (71, 195), (82, 160)], hair, width=3.2)
        art.polygon([(300, 133), (327, 197), (289, 195), (278, 160)], hair, width=3.2)
        # buns
        art.circle(88, 58, 43, hair, width=3.8)
        art.circle(272, 58, 43, hair, width=3.8)
        art.ellipse((66, 35, 111, 80), hair, hi, 2.0)
        art.ellipse((250, 35, 295, 80), hair, hi, 2.0)
        # hair ties
        art.ellipse((70, 86, 112, 108), p["accent2"], width=2.4)
        art.ellipse((248, 86, 290, 108), p["accent2"], width=2.4)
        art.circle(91, 97, 6, p["accent"], width=1.5)
        art.circle(269, 97, 6, p["accent"], width=1.5)
    elif style == "short":
        art.ellipse((60, 30, 300, 224), hair, width=3.8)
        art.polygon([(67, 122), (44, 166), (61, 189), (82, 170)], hair, width=3.0)
        art.polygon([(293, 119), (317, 157), (302, 181), (280, 162)], hair, width=3.0)
        # shaved side lines
        for i in range(3):
            art.line([(70, 139 + i * 10), (88, 132 + i * 10)], hi, 2.0)
        for i in range(3):
            art.line([(290, 139 + i * 10), (272, 132 + i * 10)], hi, 2.0)
    else:  # long
        art.ellipse((51, 25, 309, 248), hair, width=3.8)
        left_lock = [
            (62, 96),
            (33, 170),
            (37, 270),
            (52, 336),
            (98, 351),
            (88, 281),
            (94, 204),
            (78, 145),
        ]
        right_lock = [
            (298, 96),
            (327, 170),
            (323, 270),
            (308, 336),
            (262, 351),
            (272, 281),
            (266, 204),
            (282, 145),
        ]
        art.polygon(left_lock, hair, width=3.6)
        art.polygon(right_lock, hair, width=3.6)
        art.line([(56, 208), (65, 310)], hi, 3.0)
        art.line([(304, 208), (295, 310)], hi, 3.0)
    # global highlight strokes (only in back region)
    if style != "short":
        art.line(bezier([(83, 71), (118, 41), (171, 30), (213, 32)]), hi, 3.0)
        art.line(bezier([(257, 52), (283, 77), (293, 105), (294, 122)]), hi, 2.4)


def _fringe(art: Art, p: CharDict) -> None:
    hair = p["hair"]
    hi = p["hair_hi"]
    style = p["style"]
    if style == "messy":
        pts = [
            (59, 132),
            (63, 80),
            (94, 42),
            (150, 21),
            (206, 23),
            (260, 42),
            (294, 80),
            (303, 128),
            (282, 111),
            (266, 150),
            (243, 116),
            (221, 154),
            (196, 119),
            (173, 151),
            (150, 116),
            (123, 151),
            (104, 113),
            (82, 139),
        ]
        art.polygon(pts, hair, width=3.6)
        # jagged extra tufts
        art.polygon([(238, 111), (252, 146), (272, 121), (283, 157), (299, 126), (298, 95)], hair, width=2.6)
        art.line(bezier([(108, 83), (144, 50), (196, 40), (238, 49)]), hi, 3.2)
        art.line(bezier([(78, 117), (88, 93), (106, 72)]), hi, 2.6)
        # ahoge
        art.line(bezier([(176, 28), (160, 4), (191, -4), (208, 17)]), hair, 7.0, OUTLINE, 2.6)
        art.line(bezier([(176, 28), (160, 4), (191, -4), (208, 17)]), hair, 2.8)
    elif style == "buns":
        art.rounded((56, 29, 304, 144), 58, hair, width=3.6)
        art.polygon([(57, 114), (65, 156), (89, 129), (102, 165), (124, 129)], hair, width=2.8)
        art.polygon([(236, 127), (257, 166), (276, 126), (298, 157), (306, 111)], hair, width=2.8)
        art.line(bezier([(97, 68), (140, 38), (216, 34), (265, 60)]), hi, 3.4)
        art.line(bezier([(80, 100), (91, 79), (110, 62)]), hi, 2.4)
        # tiny star clip
        art.star(120, 61, 11, p["accent2"], OUTLINE, points=5)
    elif style == "short":
        art.polygon(
            [
                (61, 132),
                (64, 82),
                (94, 43),
                (157, 24),
                (232, 29),
                (288, 58),
                (303, 115),
                (279, 104),
                (265, 135),
                (240, 106),
                (215, 128),
                (188, 98),
                (159, 121),
                (133, 94),
                (102, 124),
                (82, 103),
            ],
            hair,
            width=3.4,
        )
        art.line(bezier([(111, 78), (153, 47), (209, 41), (251, 56)]), hi, 3.2)
        art.line(bezier([(261, 71), (283, 91)]), hi, 2.3)
        # small cowlick
        cowlick = bezier([(230, 30), (235, 3), (257, 2), (262, 18)])
        art.line(cowlick, hair, 6.0, OUTLINE, 2.2)
        art.line(cowlick, hair, 2.4)
    else:  # long, centre-parted
        art.polygon(
            [
                (57, 128),
                (61, 77),
                (96, 38),
                (158, 21),
                (180, 54),
                (194, 29),
                (233, 22),
                (289, 53),
                (301, 105),
                (304, 132),
                (279, 118),
                (270, 151),
                (247, 126),
                (219, 148),
                (197, 120),
                (177, 147),
                (155, 117),
                (126, 147),
                (106, 117),
                (83, 143),
            ],
            hair,
            width=3.6,
        )
        art.line([(180, 47), (180, 78)], (58, 47, 58, 120), 2.2)
        art.line(bezier([(101, 73), (142, 42), (180, 42)]), hi, 3.2)
        art.line(bezier([(257, 60), (284, 89), (292, 119)]), hi, 2.8)
        # small side braid-ish highlight
        art.line(bezier([(63, 201), (76, 254), (73, 304)]), hi, 2.8)


def _eye_open(art: Art, cx: float, cy: float, p: CharDict, look: float = 0.0) -> None:
    art.ellipse((cx - 25, cy - 27, cx + 25, cy + 28), CREAM, OUTLINE, 3.0)
    # iris
    art.ellipse((cx - 16 + look, cy - 18, cx + 16 + look, cy + 23), p["eye"], OUTLINE, 2.0)
    # pupil
    art.ellipse((cx - 7 + look, cy - 7, cx + 9 + look, cy + 17), INK, width=0)
    # highlights
    art.circle(cx - 8 + look, cy - 7, 6.2, (255, 255, 255, 255), width=0)
    art.circle(cx + 8 + look, cy + 10, 3.2, (255, 255, 255, 200), width=0)
    # upper lash
    art.curve(bezier([(cx - 25, cy - 10), (cx - 14, cy - 31), (cx + 20, cy - 28), (cx + 25, cy - 4)]), INK, 4.3)


def _brow(art: Art, cx: float, cy: float, p: CharDict, kind: str, side: int) -> None:
    hair = p["hair"]
    if kind == "angry":
        pts = [(cx - 22 * side, cy - 4), (cx + 17 * side, cy + 10)]
    elif kind == "sad":
        pts = [(cx - 22 * side, cy + 5), (cx + 17 * side, cy - 7)]
    elif kind == "smug":
        if side < 0:
            pts = [(cx - 22, cy + 1), (cx + 17, cy - 6)]
        else:
            pts = [(cx - 17, cy - 11), (cx + 22, cy - 2)]
    else:
        pts = [(cx - 20 * side, cy + 3), (cx + 15 * side, cy - 3)]
    art.curve(pts, hair, 5.2)


def _mouth(art: Art, expression: str) -> None:
    if expression in ("happy", "eat"):
        art.rounded((159, 201, 204, 229), 14, MOUTH, OUTLINE, 2.8)
        art.ellipse((172, 216, 195, 231), TONGUE, width=0)
        art.curve([(163, 203), (182, 210), (201, 203)], (255, 255, 255, 150), 2.6)
        if expression == "eat":
            for x, y, r in ((139, 223, 3), (221, 221, 2.5), (213, 234, 2)):
                art.circle(x, y, r, (230, 172, 112, 255), width=0)
    elif expression == "angry":
        art.arc((160, 204, 200, 229), 200, 340, OUTLINE, 4.4)
        art.line([(185, 233), (193, 229)], MOUTH, 2.4)
    elif expression == "hit":
        art.ellipse((158, 198, 202, 236), MOUTH, OUTLINE, 3.0)
        art.ellipse((169, 219, 194, 239), TONGUE, width=0)
    elif expression == "sleep":
        art.arc((168, 205, 193, 225), 15, 165, OUTLINE, 3.4)
        # tiny drool bubble
        art.circle(212, 227, 7, (168, 214, 235, 230), OUTLINE, 1.6)
        art.circle(224, 239, 4, (168, 214, 235, 210), OUTLINE, 1.2)
    elif expression == "sad":
        art.curve(
            [(163, 216), (171, 222), (180, 216), (189, 222), (198, 216)],
            OUTLINE,
            3.2,
        )
    elif expression == "smug":
        art.curve([(163, 214), (177, 222), (199, 210)], OUTLINE, 3.6)
        art.line([(188, 209), (201, 207)], MOUTH, 2.0)
    else:
        art.arc((166, 201, 195, 221), 20, 160, OUTLINE, 3.6)
        art.line([(180, 214), (180, 216)], OUTLINE, 2.0)


def _angry_mark(art: Art, x: float, y: float) -> None:
    red = (220, 84, 84, 255)
    art.line(bezier([(x - 17, y - 7), (x - 7, y - 3), (x - 6, y + 8)]), red, 4.0)
    art.line(bezier([(x + 17, y - 7), (x + 7, y - 3), (x + 6, y + 8)]), red, 4.0)
    art.line(bezier([(x - 7, y - 18), (x - 3, y - 7), (x + 8, y - 6)]), red, 4.0)
    art.line(bezier([(x - 7, y + 18), (x - 3, y + 7), (x + 8, y + 6)]), red, 4.0)


def _sweat(art: Art, x: float, y: float, scale: float = 1.0) -> None:
    drop = (125, 196, 227, 255)
    art.polygon(
        [(x, y - 17 * scale), (x + 12 * scale, y + 6 * scale), (x, y + 13 * scale), (x - 12 * scale, y + 6 * scale)],
        drop,
        OUTLINE,
        1.8,
    )
    art.circle(x - 4 * scale, y + 1 * scale, 2.6 * scale, (255, 255, 255, 190), width=0)


def _glasses(art: Art, p: CharDict) -> None:
    frame = (77, 88, 99, 255)
    art.ellipse((100, 143, 164, 204), None, frame, 3.2)
    art.ellipse((196, 143, 260, 204), None, frame, 3.2)
    art.line([(164, 168), (181, 162), (196, 168)], frame, 2.6)
    art.line([(100, 162), (81, 154)], frame, 2.4)
    art.line([(260, 162), (279, 154)], frame, 2.4)
    art.line([(108, 154), (121, 150)], (255, 255, 255, 155), 2.2)
    art.line([(204, 154), (217, 150)], (255, 255, 255, 155), 2.2)


def build_head(profile: CharDict, expression: str = "normal") -> Image.Image:
    p = profile
    img = canvas()
    art = Art(img)

    _back_hair(art, p)

    # ears
    art.ellipse((56, 126, 96, 181), p["skin"], width=3.2)
    art.ellipse((264, 126, 304, 181), p["skin"], width=3.2)
    art.arc((66, 145, 86, 168), 90, 270, p["blush"], 3.0)
    art.arc((274, 145, 294, 168), 270, 450, p["blush"], 3.0)

    # face
    art.ellipse((75, 66, 285, 258), p["skin"], width=3.8)
    # cheek warmth
    art.ellipse((88, 188, 148, 231), (255, 215, 196, 90), width=0)
    art.ellipse((212, 188, 272, 231), (255, 215, 196, 90), width=0)

    _fringe(art, p)

    # sideburn / side locks in front of ears
    if p["style"] in ("messy", "buns", "long"):
        art.polygon([(68, 113), (83, 103), (88, 170), (73, 194), (59, 164)], p["hair"], width=2.8)
        art.polygon([(292, 113), (277, 103), (272, 170), (287, 194), (301, 164)], p["hair"], width=2.8)
    else:
        art.polygon([(68, 121), (82, 109), (84, 154), (71, 174), (61, 151)], p["hair"], width=2.6)
        art.polygon([(292, 121), (278, 109), (276, 154), (289, 174), (299, 151)], p["hair"], width=2.6)

    expr = expression
    # brows first (under fringe is okay; they sit on face)
    if expr in ("angry", "hit", "sad", "smug"):
        brow_kind = "angry" if expr in ("angry", "hit") else ("sad" if expr == "sad" else "smug")
        _brow(art, 132, 149, p, brow_kind, -1)
        _brow(art, 228, 149, p, brow_kind, 1)
    else:
        _brow(art, 132, 151, p, "normal", -1)
        _brow(art, 228, 151, p, "normal", 1)

    if expr == "blink":
        for cx in (132, 228):
            art.arc((cx - 23, 158, cx + 23, 187), 15, 165, INK, 4.2)
            art.line([(cx - 22, 173), (cx - 28, 177)], INK, 2.2)
            art.line([(cx + 22, 173), (cx + 28, 177)], INK, 2.2)
    elif expr == "happy":
        for cx in (132, 228):
            art.curve(bezier([(cx - 22, 181), (cx - 9, 149), (cx + 11, 150), (cx + 22, 181)]), INK, 4.6)
            art.circle(cx + 12, 170, 2.4, (255, 255, 255, 170), width=0)
    elif expr == "angry":
        for cx in (132, 228):
            art.ellipse((cx - 23, 160, cx + 23, 193), CREAM, OUTLINE, 2.8)
            art.ellipse((cx - 13, 166, cx + 13, 192), p["eye"], OUTLINE, 1.8)
            art.circle(cx - 5, 172, 4.5, (255, 255, 255, 255), width=0)
            art.line([(cx - 24, 159), (cx + 22, 164)], INK, 3.4)
        art.ellipse((87, 198, 143, 218), (255, 139, 134, 160), width=0)
        art.ellipse((217, 198, 273, 218), (255, 139, 134, 160), width=0)
        _angry_mark(art, 292, 86)
    elif expr == "hit":
        for cx in (132, 228):
            art.line([(cx - 16, 157), (cx + 16, 190)], INK, 5.0)
            art.line([(cx + 16, 157), (cx - 16, 190)], INK, 5.0)
            art.circle(cx - 21, 198, 4, p["blush"], width=0)
        _sweat(art, 300, 178, 1.0)
        art.star(55, 92, 8, (255, 217, 112, 230), None)
        art.star(309, 224, 6, (255, 217, 112, 200), None)
    elif expr == "sleep":
        for cx in (132, 228):
            art.arc((cx - 23, 161, cx + 23, 189), 15, 165, INK, 4.0)
            art.line([(cx - 24, 177), (cx - 30, 181)], INK, 2.0)
        art.ellipse((88, 200, 136, 216), (255, 154, 146, 80), width=0)
        art.ellipse((224, 200, 272, 216), (255, 154, 146, 80), width=0)
    elif expr == "eat":
        for cx in (132, 228):
            art.curve(bezier([(cx - 22, 182), (cx - 10, 153), (cx + 10, 153), (cx + 22, 182)]), INK, 4.4)
        # puffed cheeks
        art.ellipse((80, 183, 146, 231), p["skin"], width=2.6)
        art.ellipse((214, 183, 280, 231), p["skin"], width=2.6)
        art.ellipse((92, 205, 130, 219), p["blush"], width=0)
        art.ellipse((230, 205, 268, 219), p["blush"], width=0)
    elif expr == "sad":
        for cx in (132, 228):
            _eye_open(art, cx, 178, p, look=-0.0)
            # lower lids
            art.line([(cx - 20, 199), (cx + 20, 199)], (255, 255, 255, 70), 1.6)
        _sweat(art, 62, 159, 0.65)
    elif expr == "smug":
        for cx in (132, 228):
            _eye_open(art, cx, 176, p, look=5.0 if cx < 180 else 3.0)
            art.rectangle((cx - 26, 151, cx + 26, 170), fill=p["skin"])
            art.line([(cx - 25, 169), (cx + 22, 166)], INK, 3.4)
            art.line([(cx + 23, 167), (cx + 29, 170)], INK, 2.2)
    else:  # normal
        _eye_open(art, 132, 175, p)
        _eye_open(art, 228, 175, p)

    if p.get("glasses"):
        _glasses(art, p)

    # nose
    art.curve(bezier([(175, 196), (182, 202), (184, 197)]), OUTLINE, 2.6)
    # blush
    if expr in ("normal", "happy", "hit", "eat", "sleep", "smug"):
        art.ellipse((93, 202, 143, 217), p["blush"], width=0)
        art.ellipse((217, 202, 267, 217), p["blush"], width=0)
        if expr in ("happy", "eat"):
            art.line([(101, 208), (116, 205)], (255, 255, 255, 90), 2.0)
            art.line([(225, 205), (240, 208)], (255, 255, 255, 90), 2.0)
    _mouth(art, expr)

    # little forehead highlight from hair
    if expr not in ("angry", "hit"):
        art.line([(119, 125), (140, 112)], (255, 255, 255, 38), 3.0)

    # expression extras: happy sparkles
    if expr == "happy":
        art.shimmer(56, 80, 8, (255, 211, 104, 210))
        art.shimmer(302, 108, 6, (255, 211, 104, 190))
    if expr == "angry":
        # tiny steam puffs
        for x, y, r in ((58, 80, 8), (42, 62, 6), (316, 73, 7)):
            art.circle(x, y, r, (255, 245, 235, 90), width=0)

    return img


def build_all_characters(out_dir: Path) -> list[CharDict]:
    """Render all character layers and return the profiles."""

    expressions = ["normal", "blink", "happy", "angry", "hit", "sleep", "eat", "sad", "smug"]
    for profile in PROFILES:
        char_dir = out_dir / profile["slug"]
        save_layer(build_body(profile, "idle"), char_dir / "body.png")
        save_layer(build_body(profile, "walk"), char_dir / "body_walk.png")
        save_layer(build_body(profile, "dangle"), char_dir / "body_dangle.png")
        parts = build_body_parts(profile, "idle")
        for name, image in parts.items():
            save_layer(image, char_dir / "parts" / f"{name}.png")
        for expression in expressions:
            save_layer(build_head(profile, expression), char_dir / "heads" / f"{expression}.png")
    return PROFILES
