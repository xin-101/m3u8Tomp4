const statusEl = document.getElementById('status');
const recentEl = document.getElementById('recent');

function sendUrl(url, title, referer) {
  chrome.runtime.sendMessage({ type: 'sendToClient', url, title, referer }, (resp) => {
    statusEl.textContent = resp && resp.ok ? '已发送到 m3u8ToMp4' : '发送失败(客户端可能未运行)';
    statusEl.style.color = resp && resp.ok ? '#22c55e' : '#ef4444';
  });
}

function refresh() {
  chrome.runtime.sendMessage({ type: 'getRecent' }, (data) => {
    recentEl.innerHTML = '';
    (data.recent || []).forEach((url) => {
      const div = document.createElement('div');
      div.className = 'item';
      div.innerHTML = `<a href="#">${url}</a>`;
      div.addEventListener('click', () => sendUrl(url, '网页视频', ''));
      recentEl.appendChild(div);
    });
    if (recentEl.children.length === 0) {
      statusEl.textContent = '最近未检测到 m3u8 请求';
    }
  });
}

document.getElementById('btnSendCurrent').addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;
  chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => {
      let found = null;
      document.querySelectorAll('video, video source').forEach((el) => {
        const s = el.src || el.currentSrc;
        if (s && s.includes('m3u8')) found = s;
      });
      if (!found) {
        const m = (document.body.innerHTML.match(/https?:[^"'\s]+\.m3u8[^"'\s]*/i) || [])[0];
        if (m) found = m;
      }
      return found;
    }
  }).then((res) => {
    const url = res && res[0] && res[0].result;
    if (url) sendUrl(url, tab.title, tab.url);
    else statusEl.textContent = '未在当前页找到 m3u8 地址';
  });
});

document.getElementById('btnSendUrl').addEventListener('click', () => {
  const url = document.getElementById('manualUrl').value.trim();
  if (url) sendUrl(url, '手动输入', '');
});

refresh();
