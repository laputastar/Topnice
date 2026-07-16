# Issue: 首页排序按钮 "Ending Soon" 仍有 ended 项目在前

## 现象
点击首页 FilterBar 的 "Ending Soon" 排序按钮，前面约 37 个项目仍然是已结束（ended）项目，预期应该是最后结束的 live 项目排最前面，ended 全部在底部。

## 已确认的信息

### 1. JSON 数据正确
`dist/index.html` 中 `#project-data` 的数据已验证：
- 共 275 个项目
- `st`（state）= `"live"` 共 270 个
- `st` = `"ended"` 共 5 个
- 全部 275 个项目都有 `st` 字段

### 2. HTML 元素正确
- 3 个 `.sort-tab` 按钮存在，`data-sort` 分别为 `"popular"`、`"newest"`、`"ending_soon"`
- 点击事件已绑定

### 3. JS 排序逻辑（最新版，在 `src/pages/index.astro` 内）

```javascript
function getFilteredData() {
  var arr = [];
  for (var i = 0; i < allData.length; i++) {
    if (currentCategory === 'all' || allData[i].c === currentCategory) {
      arr.push(allData[i]);
    }
  }
  var live = [];
  var ended = [];
  for (var j = 0; j < arr.length; j++) {
    if (arr[j].st === 'live') {
      live.push(arr[j]);
    } else {
      ended.push(arr[j]);
    }
  }
  if (currentSort === 'ending_soon') {
    live.sort(function(a,b) {
      var da = a.dl ? new Date(a.dl).getTime() : 99999999999999;
      var db = b.dl ? new Date(b.dl).getTime() : 99999999999999;
      if (isNaN(da)) da = 99999999999999;
      if (isNaN(db)) db = 99999999999999;
      return da - db;
    });
  }
  return live.concat(ended);
}

function rebuildGrid() {
  observer.disconnect();
  sentinel.style.display = 'none';
  while (grid.firstChild) { grid.removeChild(grid.firstChild); }
  var data = getFilteredData();
  for (var i = 0; i < data.length; i++) {
    grid.appendChild(makeCard(data[i]));
  }
}
```

### 4. 事件绑定

```javascript
var sortTabs = document.querySelectorAll('.sort-tab');
sortTabs.forEach(function(tab) {
  tab.addEventListener('click', function() {
    sortTabs.forEach(function(t) { t.classList.remove('active'); });
    tab.classList.add('active');
    currentSort = tab.getAttribute('data-sort');
    rebuildGrid();
  });
});
```

## 已尝试的修复
1. `.sort()` 改为 `.slice()` 拷贝后再排序（避免原数组被修改）
2. 排序后渲染全部 275 项（不再只渲染 24 项 + lazy load）
3. 用 `for` 循环替代 `.filter()` 分离 live/ended
4. 服务器端数据已改为 live→ended 顺序
5. 每次修改后均 `rm -rf dist .astro` 完全重建

## 所有排序的 ended 处理逻辑
三种排序（popular/newest/ending_soon）均使用同一模式：先分离 live 和 ended，只对 live 排序，`live.concat(ended)` 返回。

## 可能的根因猜测
- JS 执行时机问题？script is:inline 在 Layout 中的位置可能导致 DOM 未完全解析时脚本已执行，`querySelectorAll('.sort-tab')` 返回空列表？
- `rebuildGrid()` 中 `observer.disconnect()` 可能抛出异常导致后续代码不执行？
- 浏览器缓存 Old JS？已多次 `rm -rf dist .astro` 重建，但用户仍反馈无效
- 用户看到的 dist 可能不是最新的？每次重建后已重启 http.server

## 相关文件
- `src/pages/index.astro` — 排序/筛选/视图切换 JS 代码（～第 218-310 行）
- `src/components/FilterBar.astro` — 排序按钮 HTML
- `dist/index.html` — 构建产物（可直接查看 JSON 数据）
