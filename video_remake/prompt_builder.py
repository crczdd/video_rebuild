from __future__ import annotations

from . import fields as f
from .models import VideoRemakeTask

SYSTEM_PROMPT = """你是一名专业的短视频导演、商业广告导演、AI 视频生成提示词工程师和 Seedance 2.0 Mini Prompt 工程师。

你的任务不是重新创作一条视频，而是以 nanophoto提示词 为原视频结构基础，严格根据本地合并后的修改最终建议做最小必要修改，并生成一份可直接用于 Seedance 2.0 Mini 的中文最终提示词。

最高原则：用户没有要求修改的内容，不改变。保留未被修改要求覆盖的人物数量、人物关系、人物身份、剧情行为、事件顺序、分镜时序、视频节奏、镜头逻辑、对话、产品和场景。

修改优先级：
1. 台词修改 / 产品修改 / 人物修改 / 背景修改 / 痛点变化 / 特殊镜头描述
2. 修改最终建议
3. nanophoto提示词

具体修改与原 Prompt 冲突时，以具体修改为准；修改最终建议与具体字段冲突时，以具体字段为准。只允许执行用户明确要求的修改，以及为了让这些修改在剧情、镜头和视觉上逻辑成立所必需的最小关联调整。不要擅自新增或删除角色、剧情、道具、人物关系，不要大规模重写原视频。

台词必须真正替换到正确角色和对应镜头中。真人开口按对话处理；旁白或内心独白不要强行变成人物对嘴对话。产品、人物和背景只修改明确指定的属性。痛点变化需同步调整与旧痛点直接相关的症状、反应、镜头及解决后的状态，但不要重写无关剧情。特殊镜头要求若指定镜头编号或位置，应严格执行并保持前后连贯。

忽略原视频中的字幕、贴纸、促销文字、UI、水印和无意义屏幕文字。若字幕本质是人物正在说的话，只保留对话语义。最终画面默认无字幕、无水印、无贴纸、无 UI、无额外屏幕文字、无 Logo 乱码，除非用户明确要求。

如果原 nanophoto提示词 包含时间轴、镜头编号、Markdown 表格或分镜结构，应尽量保留这些有用结构，不要为了语言更漂亮而损失镜头编号、时长、动作顺序或对话信息。

不要输出分析过程、修改说明、标题、客套话或 JSON。最终只输出一份完整、连续、可直接用于 Seedance 2.0 Mini 的中文视频生成提示词正文。"""


CHANGE_INSTRUCTION_TEMPLATES = {
    f.DIALOGUE_CHANGE: (
        "台词修改：{value}。将修改后的台词真正替换进原提示词中对应角色和镜头，"
        "不要只在末尾追加修改说明。"
    ),
    f.PRODUCT_CHANGE: "产品修改：{value}。只替换明确指定的产品。",
    f.CHARACTER_CHANGE: "人物修改：{value}。只调整明确指定的人物属性。",
    f.BACKGROUND_CHANGE: "背景修改：{value}。只调整明确指定的场景和环境。",
    f.PAIN_POINT_CHANGE: (
        "痛点变化：{value}。同步调整与该痛点直接相关的表现、反应、镜头和解决后状态。"
    ),
    f.SPECIAL_SHOT: "特殊镜头描述：{value}。将要求落实到对应镜头并保持前后连贯。",
}


def build_merged_change_advice(task: VideoRemakeTask) -> str:
    """Locally merge non-empty structured changes and the general advice."""
    instructions = [
        CHANGE_INSTRUCTION_TEMPLATES[name].format(value=task.get(name))
        for name in f.SPECIFIC_CHANGE_FIELDS
        if task.get(name)
    ]
    if task.get(f.FINAL_ADVICE):
        instructions.append(f"总体修改建议：{task.get(f.FINAL_ADVICE)}")
    return "\n".join(instructions)


def build_user_prompt(task: VideoRemakeTask) -> str:
    merged_advice = build_merged_change_advice(task)
    return (
        f"【原始 nanophoto提示词】\n{task.get(f.NANOPHOTO_PROMPT)}\n\n"
        f"【本地合并后的修改最终建议】\n{merged_advice}\n\n"
        "【生成要求】\n"
        "请以原始 nanophoto提示词为基础执行上述修改。只修改建议明确涉及的内容，"
        "其余未提及的角色、人物关系、剧情行为、事件顺序、动作、镜头、对话、产品、"
        "背景和节奏全部保持不变；只允许为保证修改后逻辑成立而做最小关联调整。"
        "请直接输出一份完整、可用于 Seedance 2.0 Mini 的中文视频生成提示词正文，"
        "不要输出分析、修改说明、标题、客套话或 JSON。"
    )
