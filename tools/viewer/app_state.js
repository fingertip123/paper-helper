/* 研栈前端状态 Store（P1）：论文库 / Wiki / 上传 集中管理 */
const AppState = {
  wiki: { data: null, tc: null, nodemap: {} },
  library: {
    filter: "all",
    groupTab: "all",
    groupId: "",
    search: "",
    sort: "ingested_desc",
    view: "card",
    dragSid: null,
    animTimer: null,
  },
  upload: { reuploadTargetId: "" },
  list: { search: "", hits: null },
  drawer: { stack: [] },
  topics: {
    list: [],
    current: "",
    purposeFields: [],
    rulesCache: {},
    activeRuleTab: "purpose",
    newTopicImportFrom: "",
  },
  service: { up: false },
  analysis: {
    deepKey: null, deepStage: "分析中…", deepPoll: null,
    stdKey: null, stdStage: "分析中…", stdPoll: null,
  },
  initWikiData(odata) {
    this.wiki.data = odata;
    this.wiki.tc = odata && odata.typeconfig;
    this.rebuildNodeMap();
  },
  rebuildNodeMap() {
    const omap = {};
    (this.wiki.data && this.wiki.data.nodes || []).forEach(n => { omap[n.id] = n; });
    this.wiki.nodemap = omap;
  },
  clearLibraryUi() {
    this.library.filter = "all";
    this.library.groupTab = "all";
    this.library.groupId = "";
    this.library.search = "";
  },
};

/* 向后兼容：旧全局变量代理到 Store */
Object.defineProperty(window, "DATA", {
  get() { return AppState.wiki.data; },
  set(v) { AppState.initWikiData(v); },
  configurable: true,
});
Object.defineProperty(window, "TC", {
  get() { return AppState.wiki.tc; },
  set(v) { AppState.wiki.tc = v; },
  configurable: true,
});
Object.defineProperty(window, "NODEMAP", {
  get() { return AppState.wiki.nodemap; },
  set(v) { AppState.wiki.nodemap = v; },
  configurable: true,
});
Object.defineProperty(window, "LIB_FILTER", {
  get() { return AppState.library.filter; },
  set(v) { AppState.library.filter = v; },
  configurable: true,
});
Object.defineProperty(window, "LIB_GROUP_TAB", {
  get() { return AppState.library.groupTab; },
  set(v) { AppState.library.groupTab = v; },
  configurable: true,
});
Object.defineProperty(window, "LIB_GROUP_ID", {
  get() { return AppState.library.groupId; },
  set(v) { AppState.library.groupId = v; },
  configurable: true,
});
Object.defineProperty(window, "LIB_SEARCH", {
  get() { return AppState.library.search; },
  set(v) { AppState.library.search = v; },
  configurable: true,
});
Object.defineProperty(window, "LIB_SORT", {
  get() { return AppState.library.sort; },
  set(v) { AppState.library.sort = v; },
  configurable: true,
});
Object.defineProperty(window, "LIB_VIEW", {
  get() { return AppState.library.view; },
  set(v) { AppState.library.view = v; },
  configurable: true,
});
Object.defineProperty(window, "REUPLOAD_TARGET_ID", {
  get() { return AppState.upload.reuploadTargetId; },
  set(v) { AppState.upload.reuploadTargetId = v; },
  configurable: true,
});
Object.defineProperty(window, "LIST_SEARCH", {
  get() { return AppState.list.search; },
  set(v) { AppState.list.search = v; },
  configurable: true,
});
Object.defineProperty(window, "LIST_SEARCH_HITS", {
  get() { return AppState.list.hits; },
  set(v) { AppState.list.hits = v; },
  configurable: true,
});
Object.defineProperty(window, "DRAWER_STACK", {
  get() { return AppState.drawer.stack; },
  set(v) { AppState.drawer.stack = v; },
  configurable: true,
});
