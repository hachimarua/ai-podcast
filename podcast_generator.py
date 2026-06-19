import os
import re
import glob
import socket
import shutil
from datetime import datetime
import xml.etree.ElementTree as ET
from xml.dom import minidom

# 設定
PORT = 8000
EPISODES_DIR = "episodes"
FEED_FILENAME = "podcast.xml"

# ポッドキャスト情報
PODCAST_TITLE = "朝の5分AI学習ラジオ"
PODCAST_DESCRIPTION = "Notionに蓄積したAI用語の復習と、ホワイトリストソースから収集した最新AIニュースを掛け合わせた、毎朝の自律学習ポッドキャストです。"
PODCAST_LANGUAGE = "ja"

def get_local_ip():
    """同一Wi-Fi上のiPhoneからアクセスするためのMacのローカルIPアドレスを自動検出"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 実際に接続は行わないダミーの接続先
        s.connect(('10.254.254.254', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = 'localhost'
    finally:
        s.close()
    return ip

def get_rfc2822_date(filepath):
    """ファイルの作成日時をポッドキャスト規格(RFC 2822)の日付文字列に変換"""
    mtime = os.path.getmtime(filepath)
    dt = datetime.fromtimestamp(mtime)
    # RFC 2822フォーマット: Mon, 02 Jan 2006 15:04:05 -0700
    # 日本時間 (UTC+9) としてフォーマット
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0900")

def archive_today_podcast():
    """本日の音声ファイルをepisodesディレクトリに日付付きでアーカイブコピー"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    source_path = os.path.join(base_dir, "todays_podcast.mp3")
    
    if not os.path.exists(source_path):
        print(f"[Warning] Archive source 'todays_podcast.mp3' not found. Skipping archive.")
        return None
        
    episodes_path = os.path.join(base_dir, EPISODES_DIR)
    os.makedirs(episodes_path, exist_ok=True)
    
    # 日付付きのファイル名を作成 (例: episodes/podcast_20260619_073000.mp3)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_filename = f"podcast_{timestamp}.mp3"
    dest_path = os.path.join(episodes_path, dest_filename)
    
    shutil.copy2(source_path, dest_path)
    print(f"Archived today's podcast to: {dest_path}")
    return dest_filename

def generate_podcast_rss():
    """episodesフォルダ内のMP3ファイルを元にpodcast.xmlを再構築"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    episodes_path = os.path.join(base_dir, EPISODES_DIR)
    
    if not os.path.exists(episodes_path):
        os.makedirs(episodes_path, exist_ok=True)
        
    # episodes内のMP3ファイルを全検索
    mp3_files = glob.glob(os.path.join(episodes_path, "*.mp3"))
    # 作成日時が新しい順にソート
    mp3_files.sort(key=os.path.getmtime, reverse=True)
    
    # 環境変数からベースURLを取得、なければローカルIPを自動検出
    base_url = os.getenv("BASE_URL")
    if not base_url:
        local_ip = get_local_ip()
        base_url = f"http://{local_ip}:{PORT}"
    else:
        base_url = base_url.rstrip("/")
    
    # XMLルート要素の作成
    rss = ET.Element("rss", {
        "version": "2.0",
        "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/"
    })
    
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = PODCAST_TITLE
    ET.SubElement(channel, "description").text = PODCAST_DESCRIPTION
    ET.SubElement(channel, "link").text = base_url
    ET.SubElement(channel, "language").text = PODCAST_LANGUAGE
    
    # iTunes用の基本メタデータ
    ET.SubElement(channel, "itunes:author").text = "Antigravity Agent"
    ET.SubElement(channel, "itunes:summary").text = PODCAST_DESCRIPTION
    # itunes:categoryを追加
    category = ET.SubElement(channel, "itunes:category", {"text": "Technology"})
    
    # エピソードの追加
    for mp3_path in mp3_files:
        filename = os.path.basename(mp3_path)
        file_size = os.path.getsize(mp3_path)
        pub_date = get_rfc2822_date(mp3_path)
        
        # ファイル名から日付をパースして表示用にする (例: podcast_20260619_104300.mp3 -> 2026年06月19日のAIラジオ)
        match = re.search(r"podcast_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", filename)
        if match:
            year, month, day, hour, minute, second = match.groups()
            ep_title = f"{year}年{month}月{day}日 {hour}:{minute} のAI学習ラジオ"
        else:
            ep_title = f"AI学習ラジオ ({filename})"
            
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = ep_title
        ET.SubElement(item, "description").text = f"本日の復習用語を交えた最新AIニュースの要約解説です。"
        ET.SubElement(item, "pubDate").text = pub_date
        
        # 音声エンクロージャ (MP3へのURL、サイズ、タイプ)
        media_url = f"{base_url}/{EPISODES_DIR}/{filename}"
        ET.SubElement(item, "enclosure", {
            "url": media_url,
            "length": str(file_size),
            "type": "audio/mpeg"
        })
        
        # iTunesメタデータ
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = filename
        ET.SubElement(item, "itunes:author").text = "Antigravity Agent"
        # 概算の再生時間 (128kbps想定: 1秒あたりおよそ16KB)
        duration_sec = int(file_size / (16 * 1024))
        m, s = divmod(duration_sec, 60)
        ET.SubElement(item, "itunes:duration").text = f"{m:02d}:{s:02d}"

    # インデントして整形したXMLを書き出す
    xml_str = ET.tostring(rss, encoding="utf-8")
    reparsed = minidom.parseString(xml_str)
    pretty_xml = reparsed.toprettyxml(indent="  ", encoding="utf-8")
    
    xml_path = os.path.join(base_dir, FEED_FILENAME)
    with open(xml_path, "wb") as f:
        f.write(pretty_xml)
        
    print(f"Generated Podcast RSS feed at: {xml_path}")
    print("\n" + "="*50)
    print("【CarPlay / iPhone へのポッドキャスト登録案内】")
    print(f"1. Mac上でサーバーが起動していることを確認してください。")
    print(f"2. 同一のWi-FiネットワークにiPhoneを接続します。")
    print(f"3. iPhoneの「ポッドキャスト」アプリを開きます。")
    print(f"4. 「ライブラリ」タブを開き、右上の「…」から「URLで番組を追加」を選択。")
    print(f"5. 以下のURLを入力して追加します：")
    print(f"   {base_url}/{FEED_FILENAME}")
    print("="*50 + "\n")

if __name__ == "__main__":
    # アーカイブを実行してXMLを生成するテスト
    archive_today_podcast()
    generate_podcast_rss()
