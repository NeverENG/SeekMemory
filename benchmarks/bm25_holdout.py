"""独立冻结的 BM25 验收数据；作者未运行检索、校准或观察模型输出。

全部为合成文本。预期由问题语义人工指定，不能按实现结果修改。
该集只用于参数冻结后的验收，不得用于选择归一化常量或权重。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HoldoutDocument:
    id: str
    text: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class HoldoutCase:
    id: str
    query: str
    target: HoldoutDocument
    distractors: tuple[HoldoutDocument, ...]
    reason: str

    @property
    def expected_target_id(self) -> str:
        """返回由人工问题语义指定的唯一目标 ID。"""
        return self.target.id


HOLDOUT_CASES = (
    HoldoutCase(
        "rare_instrument",
        "上次聊天我说最近准备开始陶笛十二孔入门练习，你还记得当时我是怎么安排的吗",
        HoldoutDocument("instrument_target", "陶笛十二孔入门练习安排在周日下午三点，老师要求自带乐器。"),
        (
            HoldoutDocument("instrument_noise_01", "上次聊天我说最近准备开始整理衣柜，当时安排在周六。"),
            HoldoutDocument("instrument_noise_02", "上次聊天我说最近准备开始跑步，当时安排在每天清晨。"),
            HoldoutDocument("instrument_noise_03", "上次聊天我说最近准备开始做饭，当时先买了蒸锅。"),
            HoldoutDocument("instrument_noise_04", "上次聊天我说最近准备开始养花，当时把花盆放阳台。"),
            HoldoutDocument("instrument_noise_05", "上次聊天我说最近准备开始读书，当时选了推理小说。"),
            HoldoutDocument("instrument_noise_06", "上次聊天我说最近准备开始记账，当时先整理了票据。"),
            HoldoutDocument("instrument_noise_07", "上次聊天我说最近准备开始学游泳，当时报名了周四晚班。"),
            HoldoutDocument("instrument_noise_08", "上次聊天我说最近准备开始旅行，当时想去福建。"),
            HoldoutDocument("instrument_noise_09", "上次聊天我说最近准备开始画画，当时买了水彩纸。"),
            HoldoutDocument("instrument_noise_10", "上次聊天我说最近准备开始摄影，当时借了朋友的镜头。"),
        ),
        "稀有乐器短语应压过重复的聊天套话；其余文档只讲其他活动。",
    ),
    HoldoutCase(
        "long_travel_note",
        "上次聊到旅行的时候，我说在青海湖回程车上遗落的百年孤独最后找到了吗",
        HoldoutDocument(
            "travel_target",
            "那次西北旅行先坐火车到西宁，早饭吃了牛肉面，随后包车去湖边。"
            "司机介绍了沿途的山和牧场，午后遇到阵雨，我们在路边等了一会儿。"
            "青海湖回程车上遗落的百年孤独被司机放在副驾驶，第二天已送回旅馆。"
            "回去前还买了酸奶，并按原计划乘晚班火车离开。",
        ),
        (
            HoldoutDocument("travel_noise_01", "上次聊到旅行的时候，我说在苏州回程车上找到了落下的围巾。"),
            HoldoutDocument("travel_noise_02", "上次聊到旅行的时候，我说在桂林回程车上听了一路音乐。"),
            HoldoutDocument("travel_noise_03", "上次聊到旅行的时候，我说在长沙回程车上吃完了点心。"),
            HoldoutDocument("travel_noise_04", "上次聊到旅行的时候，我说在厦门回程车上整理了照片。"),
            HoldoutDocument("travel_noise_05", "上次聊到旅行的时候，我说在成都回程车上睡了一觉。"),
            HoldoutDocument("travel_noise_06", "上次聊到旅行的时候，我说在南京回程车上买好了下次的票。"),
            HoldoutDocument("travel_noise_07", "上次聊到旅行的时候，我说在武汉回程车上看到了晚霞。"),
            HoldoutDocument("travel_noise_08", "上次聊到旅行的时候，我说在大理回程车上联系了同学。"),
            HoldoutDocument("travel_noise_09", "上次聊到旅行的时候，我说在泉州回程车上收到家人消息。"),
            HoldoutDocument("travel_noise_10", "上次聊到旅行的时候，我说在洛阳回程车上看完了杂志。"),
        ),
        "目标事实位于较长记忆中；其他旅行同样有回程车上等套话但无目标书籍。",
    ),
    HoldoutCase(
        "tagged_spare_item",
        "之前说过的隐形眼镜备用物品，放在办公室什么地方来着",
        HoldoutDocument(
            "spare_target", "备用的那盒放在右手边第二格抽屉，周五补进去两副。",
            ("隐形眼镜", "备用物品", "办公室"),
        ),
        (
            HoldoutDocument("spare_noise_01", "之前说过的雨伞放在办公室门口。", ("雨伞", "办公室")),
            HoldoutDocument("spare_noise_02", "之前说过的便签放在办公室桌面。", ("便签", "办公室")),
            HoldoutDocument("spare_noise_03", "之前说过的订书机放在办公室柜顶。", ("订书机", "办公室")),
            HoldoutDocument("spare_noise_04", "之前说过的茶叶放在办公室茶水间。", ("茶叶", "办公室")),
            HoldoutDocument("spare_noise_05", "之前说过的毛毯放在办公室椅背。", ("毛毯", "办公室")),
            HoldoutDocument("spare_noise_06", "之前说过的文件袋放在办公室书架。", ("文件袋", "办公室")),
            HoldoutDocument("spare_noise_07", "之前说过的绿植放在办公室窗边。", ("绿植", "办公室")),
            HoldoutDocument("spare_noise_08", "之前说过的耳机放在办公室电脑旁。", ("耳机", "办公室")),
            HoldoutDocument("spare_noise_09", "之前说过的水杯放在办公室餐盘架。", ("水杯", "办公室")),
            HoldoutDocument("spare_noise_10", "之前说过的充电线放在办公室工具包。", ("充电线", "办公室")),
        ),
        "正文用那盒代称，物品名称由标签提供；仅共享办公室不能回答问题。",
    ),
    HoldoutCase(
        "mixed_identifier",
        "你还记得上次我说给键盘设置的 QMK Tap Dance 双击动作是什么吗",
        HoldoutDocument(
            "keyboard_target", "QMK Tap Dance 的双击动作设为切换中文输入；单击仍输入右 Shift。",
            ("键盘", "QMK"),
        ),
        (
            HoldoutDocument("keyboard_noise_01", "你还记得上次我说给键盘设置的背光亮度是五成吗。"),
            HoldoutDocument("keyboard_noise_02", "你还记得上次我说给键盘设置的休眠时间是十分钟吗。"),
            HoldoutDocument("keyboard_noise_03", "你还记得上次我说给键盘设置的颜色是浅蓝色吗。"),
            HoldoutDocument("keyboard_noise_04", "你还记得上次我说给键盘设置的有线模式已经保存了吗。"),
            HoldoutDocument("keyboard_noise_05", "你还记得上次我说给键盘设置的音量旋钮仍能使用吗。"),
            HoldoutDocument("keyboard_noise_06", "你还记得上次我说给键盘设置的宏录制已经关闭了吗。"),
            HoldoutDocument("keyboard_noise_07", "你还记得上次我说给键盘设置的方向键仍在右下角吗。"),
            HoldoutDocument("keyboard_noise_08", "你还记得上次我说给键盘设置的蓝牙名称换成书房了吗。"),
            HoldoutDocument("keyboard_noise_09", "你还记得上次我说给键盘设置的灯效速度调慢了吗。"),
            HoldoutDocument("keyboard_noise_10", "你还记得上次我说给键盘设置的电量提醒已经打开了吗。"),
        ),
        "中英文标识与中文动作同时出现；干扰项只讨论其他键盘设置。",
    ),
    HoldoutCase(
        "common_conversation_prefix",
        "我们之前聊天的时候我提过，周末去白石洲旧书市集卖完的那套版画是谁买走的",
        HoldoutDocument(
            "market_target", "白石洲旧书市集那套版画被隔壁摊位的阿姨买走，她说要送给外孙。",
        ),
        (
            HoldoutDocument("market_noise_01", "我们之前聊天的时候我提过，周末去公园散步时买了一瓶水。"),
            HoldoutDocument("market_noise_02", "我们之前聊天的时候我提过，周末去菜市场时忘带购物袋。"),
            HoldoutDocument("market_noise_03", "我们之前聊天的时候我提过，周末去商场时看见一双鞋。"),
            HoldoutDocument("market_noise_04", "我们之前聊天的时候我提过，周末去海边时遇到下雨。"),
            HoldoutDocument("market_noise_05", "我们之前聊天的时候我提过，周末去图书馆时带回两本书。"),
            HoldoutDocument("market_noise_06", "我们之前聊天的时候我提过，周末去美术馆时排了半小时。"),
            HoldoutDocument("market_noise_07", "我们之前聊天的时候我提过，周末去体育馆时换了储物柜。"),
            HoldoutDocument("market_noise_08", "我们之前聊天的时候我提过，周末去花店时挑了白色的花。"),
            HoldoutDocument("market_noise_09", "我们之前聊天的时候我提过，周末去面包店时买了可颂。"),
            HoldoutDocument("market_noise_10", "我们之前聊天的时候我提过，周末去车站时捡到一枚硬币。"),
        ),
        "重复聊天套话不得压过地点、物品及买家的具体事实。",
    ),
)

# 用于相同候选池的无证据检查；这些查询的词项没有出现在以上正文或标签里。
NO_RESULT_QUERIES = ("宇宙弦量子引力", "苔藓孢子繁殖")


@dataclass(frozen=True)
class SemanticLimit:
    query: str
    memory: str


# 语义相关但无共同 bigram；不作为本次 BM25 必须命中的用例。
SEMANTIC_LIMITS = (
    SemanticLimit("我是干什么的", "量化交易项目开发"),
    SemanticLimit("我靠啥谋生", "职业是牙科医生"),
)
