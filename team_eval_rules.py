TEAM_EVALUATION_CONFIG = {
    "maxItems": 3,
    "strongThreshold": 1.25,
    "eliteThreshold": 1.6,
    "weakThreshold": 0.75,
    "criticalThreshold": 0.45,
    "mvpFocusThreshold": 1.5,
    "mvpQuietThreshold": 0.5,
    "perGameMetrics": [
        {
            "column": "KDA得分",
            "label": "KDA得分",
            "types": ["英雄", "步兵", "哨兵", "无人机"],
        },
        {
            "column": "对敌伤害量",
            "label": "局均对敌伤害",
            "types": ["英雄", "步兵", "哨兵", "无人机"],
        },
        {
            "column": "建筑伤害",
            "label": "建筑伤害",
            "types": ["英雄", "步兵", "哨兵", "无人机", "飞镖"],
        },
        {
            "column": "场均击杀数",
            "label": "场均击杀",
            "types": ["英雄", "步兵", "哨兵", "无人机"],
        },
        {
            "column": "场均助攻数",
            "label": "场均助攻",
            "types": ["英雄", "步兵", "哨兵", "无人机"],
        },
        {
            "column": "场均死亡数",
            "label": "场均死亡",
            "types": ["英雄", "步兵", "哨兵", "无人机", "工程"],
            "lowerIsBetter": True,
        },
        {
            "column": "局均组装经济数",
            "fallbackColumns": ["局均兑换经济数"],
            "label": "局均工程经济",
            "types": ["工程"],
        },
        {
            "column": "局均组装成功次数",
            "label": "局均组装成功",
            "types": ["工程"],
        },
        {
            "column": "局均雷达分数",
            "fallbackColumns": ["双倍易伤时间"],
            "label": "局均雷达收益",
            "types": ["雷达"],
        },
        {
            "column": "总场次飞镖分数",
            "fallbackColumns": ["建筑伤害"],
            "label": "飞镖目标收益",
            "types": ["飞镖"],
        },
    ],
    "axisTips": {
        "英雄": "重火力与关键破甲表现突出时，适合承担压制和拆建筑节奏。",
        "步兵": "正面交火稳定性会直接影响整队交换质量。",
        "步兵3": "MVP 分布偏高时，说明该步兵位在队内高光局里更常承担核心输出。",
        "步兵4": "MVP 分布偏高时，说明该步兵位在队内高光局里更常承担核心输出。",
        "哨兵": "哨兵强势通常能抬高防线容错，并给前场创造更舒服的节奏。",
        "无人机": "无人机轴高说明空中火力或收割能力更容易形成局部优势。",
        "雷达": "雷达轴高说明信息收益、易伤或反制能力对团队贡献更明显。",
        "工程": "工程轴高通常代表经济循环更顺，能支撑中后期装备和兑换节奏。",
        "飞镖": "飞镖轴高说明目标命中或建筑压力更容易形成战略收益。",
    },
}


def get_team_evaluation_config():
    return TEAM_EVALUATION_CONFIG
