import time
import logging
from datetime import datetime

logging.basicConfig(
    filename='loop_log.txt',
    level=logging.ERROR,
    format='%(asctime)s - %(message)s'
)

INTERVAL_SECONDS = 3600

POST_TEMPLATES = [
    """1万以下でノイキャン最強クラス、これ知らないと損。

・Soundcore P40iが9千円台で買える
・ノイキャン性能、値段を完全に裏切る
・ケースがスマホスタンドになって便利
・音質は正直もう少し欲しいとこあり

紹介ガジェットのAmazonリンクはプロフのまとめURLへ！
#イヤホン #ガジェット紹介""",

    """通学中に集中できないの、イヤホンのせいかも。

・P40iのノイキャンで電車の雑音消える
・1万以下でここまで遮音できるのは本物
・ケースをスタンドにしてスマホも見やすい
・装着感は人によって合う合わないあり

紹介ガジェットのAmazonリンクはプロフのまとめURLへ！
#イヤホン #コスパガジェット""",

    """バイト3回分で、図書館レベルの静寂を作れる。

・Anker P40i、9千円台で買えるやつ
・ノイキャンで満員電車が別世界になる
・スタンド兼ケースで机上ですっきり
・長時間装着は少し蒸れる点だけ注意

紹介ガジェットのAmazonリンクはプロフのまとめURLへ！
#ノイキャン #学生ガジェット"""
]

current_index = 0

def my_task():
    global current_index
    tweet_text = POST_TEMPLATES[current_index]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("toukou_list.txt", "a", encoding="utf-8") as f:
        f.write(f"=============== 【生成日時: {now_str}】 ===============\n")
        f.write(tweet_text + "\n")
        f.write("=====================================================\n\n")
    print(f"【成功】修正版の下書きを toukou_list.txt にストックしました")
    current_index = (current_index + 1) % len(POST_TEMPLATES)

while True:
    try:
        my_task()
    except Exception as e:
        logging.error(f"エラー発生: {e}")
        print(f"【エラー発生】処理をスキップして次へ進みます: {e}")
    print(f"{INTERVAL_SECONDS}秒後に次のストックを実行します...")
    time.sleep(INTERVAL_SECONDS)
