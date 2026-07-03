const { reactive, watch } = Vue;

const STORAGE_KEY = 'sonus-form';

const store = reactive({
  // API data
  models: [],
  voices: {},
  voiceDetails: [],
  sfx: [],
  sfxDetails: [],
  outputs: [],

  // Form
  form: {
    model: '',
    text: '',
    speaker_name: '',
    voice_description: '',
    sample_voice_file: '',
    speed: 1.0,
    temperature: 0,
    seed: null,
    add_pauses: true,
    exaggeration: 0.1,
    cfg_weight: 0.0,
  },

  // Audio player
  currentAudio: null,
  currentName: null,

  // Filters
  filterState: { engine: '', model: '', time: '' },

  // Modals
  showAddVoice: false,
  showParams: false,
  showManage: false,
  showResetConfirm: false,
  regenParams: null,
  modalOut: null,

  // Curl
  curlOpen: false,

  // Blend mode (voice_blend models)
  blendMode: false,
  blendSelections: {},

  // Batch mode
  batchMode: false,
  batchTab: 'clone',
  selectedBatchModels: [],
  multivoiceModel: '',
  multivoiceSelectedVoices: [],
  batchGapMs: 2000,
  batchProgress: null,
  batchAbort: false,
  batchSummary: null,

  // Output grouping
  groupByBatch: false,
  showBatchDetail: false,
  batchDetailItems: [],
  batchDetailLabel: '',

  // E2E validation
  e2eEnabled: false,
  e2eModel: '',
  e2eLanguage: '',
  e2eModels: [],
  e2eResults: [],

  // Generation status
  genStatus: '',
  genStatusClass: '',

  // Advanced section
  showAdvanced: false,

  // Presets
  presets: [],
  showSavePreset: false,
  savePresetStatus: '',
  savePresetStatusClass: '',

  // Upload / record status
  uploadStatus: '',
  uploadStatusClass: '',
  recordStatus: '',
  recordStatusClass: '',

  // Loading state
  loading: false,
  outputsLoading: true,

  // Rename state
  renaming: null, // { original: string, current: string } or null

  // Tab mode
  activeTab: 'generate', // 'generate' | 'transcribe'

  // Transcribe form
  transcribeForm: {
    audioSource: 'file',  // 'file' | 'record' | 'url'
    uploadFile: null,
    recordName: '',
    urlAddress: '',
    stagedFiles: [],
    activeFileIndex: 0,
    model: '',
    language: '',
  },

  // Transcribe recording
  transcribeRecording: false,
  transcribeRecorder: null,
  transcribeChunks: [],
  transcribeCtx: null,
  transcribeAnalyser: null,
  transcribeAnimFrame: null,
  transcribeStream: null,

  // Transcribe audio player (for staged audio preview)
  transcribePlaying: false,
  transcribeCurrentTime: 0,
  transcribeDuration: 0,
  transcribeSeeker: false,
  transcribeAudioEl: null,

  // Transcribe status
  transcribeStatus: '',
  transcribeStatusClass: '',
  transcribeLoading: false,
  transcribeResults: [],

  // Batch transcribe
  batchTranscribeMode: false,
  selectedTranscribeModels: [],
  batchTranscribeProgress: null,
  batchTranscribeAbort: false,
  batchTranscribeResults: [],
  batchTranscribeSummary: null,
});

// Shared helper — transform /v1/voices data into store.voices + store.voiceDetails
function applyVoiceData($store, list) {
  const map = {};
  const details = [];
  list.forEach(v => {
    if (!map[v.engine]) map[v.engine] = {};
    const cat = v.category === 'cloneable' ? 'cloneable' : v.language || 'built_in';
    if (!map[v.engine][cat]) map[v.engine][cat] = [];
    map[v.engine][cat].push(v.id);
    if (v.category === 'cloneable') {
      details.push({ name: v.id, size: v.size, duration: v.duration, created_at: v.created_at, url: v.url });
    }
  });
  details.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
  $store.voices = map;
  $store.voiceDetails = details;
}

const E2E_KEY = 'sonus-e2e';

// Persist form to localStorage
watch(() => store.form, (val) => {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...val })); } catch {}
}, { deep: true });

// Restore form from localStorage
try {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) Object.assign(store.form, JSON.parse(saved));
} catch {}

// Persist e2e state
watch(() => ({ e2eEnabled: store.e2eEnabled, e2eModel: store.e2eModel, e2eLanguage: store.e2eLanguage }), (val) => {
  try { localStorage.setItem(E2E_KEY, JSON.stringify(val)); } catch {}
}, { deep: true });

// Restore e2e state
try {
  const saved = localStorage.getItem(E2E_KEY);
  if (saved) Object.assign(store, JSON.parse(saved));
} catch {}

const UI_KEY = 'sonus-ui';

// Persist UI state (tab selection, batch modes)
watch(() => ({ activeTab: store.activeTab, batchMode: store.batchMode, batchTab: store.batchTab, batchTranscribeMode: store.batchTranscribeMode }), (val) => {
  try { localStorage.setItem(UI_KEY, JSON.stringify(val)); } catch {}
}, { deep: true });

// Restore UI state
try {
  const saved = localStorage.getItem(UI_KEY);
  if (saved) Object.assign(store, JSON.parse(saved));
} catch {}

const TRANS_KEY = 'sonus-transcribe';

// Persist transcribe form
watch(() => ({ model: store.transcribeForm.model, language: store.transcribeForm.language, audioSource: store.transcribeForm.audioSource }), (val) => {
  try { localStorage.setItem(TRANS_KEY, JSON.stringify(val)); } catch {}
}, { deep: true });

// Restore transcribe form
try {
  const saved = localStorage.getItem(TRANS_KEY);
  if (saved) Object.assign(store.transcribeForm, JSON.parse(saved));
} catch {}
