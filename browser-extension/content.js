// 内容脚本: 页面加载后收集可见的 m3u8 视频源并上报
(function () {
  function collect() {
    const urls = [];
    document.querySelectorAll('video, video source').forEach((el) => {
      const src = el.src || el.currentSrc;
      if (src && src.toLowerCase().includes('m3u8')) urls.push(src);
    });
    if (urls.length) {
      chrome.runtime.sendMessage({ type: 'foundM3u8', urls }, () => {});
    }
  }
  if (document.readyState === 'complete') collect();
  else window.addEventListener('load', collect);
})();
