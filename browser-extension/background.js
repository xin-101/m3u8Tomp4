const API_BASE = 'http://127.0.0.1:18888';

// 右键菜单: 发送当前页面到客户端(自动提取m3u8)
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: 'sendToM3u8ToMp4',
    title: '发送到 m3u8ToMp4',
    contexts: ['page', 'link']
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== 'sendToM3u8ToMp4') return;
  const url = info.linkUrl || info.pageUrl || tab.url;
  if (!url) return;

  let m3u8 = url;
  if (!m3u8.toLowerCase().includes('.m3u8')) {
    // 尝试从页面提取 m3u8 地址
    const extracted = await extractM3u8FromTab(tab.id);
    m3u8 = extracted || url;
  }
  await sendToClient(m3u8, tab.title || '网页视频', tab.url || '');
});

// 检测 webRequest 中的 m3u8 请求
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (!details.url || !details.url.toLowerCase().includes('.m3u8')) return;
    const key = 'found_' + details.url;
    chrome.storage.session.set({ [key]: details.url });
    chrome.action.setBadgeText({ text: 'M3U8' });
    chrome.action.setBadgeBackgroundColor({ color: '#3b82f6' });
    // 缓存最近5条
    chrome.storage.session.get(['recent'], (data) => {
      const recent = data.recent || [];
      if (!recent.includes(details.url)) {
        recent.unshift(details.url);
        chrome.storage.session.set({ recent: recent.slice(0, 5) });
      }
    });
  },
  { urls: ['<all_urls>'] }
);

async function extractM3u8FromTab(tabId) {
  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        const sources = [];
        document.querySelectorAll('video source, video').forEach((el) => {
          const src = el.src || el.currentSrc;
          if (src && src.includes('m3u8')) sources.push(src);
        });
        const scripts = Array.from(document.scripts).map((s) => s.textContent || '');
        for (const script of scripts) {
          const match = script.match(/["'](https?:\/\/[^"']+\.m3u8[^"']*)["']/i);
          if (match) sources.push(match[1]);
        }
        return sources[0] || null;
      }
    });
    return result && result.result ? result.result : null;
  } catch (e) {
    return null;
  }
}

async function sendToClient(url, title, referer) {
  try {
    const resp = await fetch(API_BASE + '/api/task', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, title, referer })
    });
    const data = await resp.json();
    if (data.ok) {
      chrome.action.setBadgeText({ text: 'OK' });
      setTimeout(() => chrome.action.setBadgeText({ text: '' }), 2000);
    } else {
      chrome.action.setBadgeText({ text: 'ERR' });
      setTimeout(() => chrome.action.setBadgeText({ text: '' }), 2000);
    }
  } catch (e) {
    chrome.action.setBadgeText({ text: 'OFF' });
    setTimeout(() => chrome.action.setBadgeText({ text: '' }), 2000);
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === 'sendToClient') {
    sendToClient(msg.url, msg.title || '网页视频', msg.referer || '').then(() => sendResponse({ ok: true }));
    return true;
  }
  if (msg && msg.type === 'getRecent') {
    chrome.storage.session.get(['recent'], (data) => sendResponse({ recent: data.recent || [] }));
    return true;
  }
  if (msg && msg.type === 'foundM3u8') {
    chrome.storage.session.get(['recent'], (data) => {
      const recent = data.recent || [];
      (msg.urls || []).forEach((u) => {
        if (!recent.includes(u)) recent.unshift(u);
      });
      chrome.storage.session.set({ recent: recent.slice(0, 5) });
      chrome.action.setBadgeText({ text: 'M3U8' });
      chrome.action.setBadgeBackgroundColor({ color: '#3b82f6' });
    });
    sendResponse({ ok: true });
    return true;
  }
});
