(function () {
const comps = window.__comps = {};

function buildVoiceForCapabilities(caps, store) {
  if (caps.includes('voice_blend') && store.blendMode) {
    const selections = store.blendSelections;
    const keys = Object.keys(selections);
    if (keys.length) {
      const parts = keys.map(k => {
        const w = selections[k];
        return keys.length > 1 ? k + ':' + w.toFixed(2) : k;
      });
      return parts.join(',');
    }
  }
  if (caps.includes('speaker') || caps.includes('voice_blend')) {
    return store.form.speaker_name.trim();
  }
  if (caps.includes('voice_prompt')) {
    return store.form.voice_description.trim();
  }
  if (caps.includes('voice_clone')) {
    return store.form.sample_voice_file.trim();
  }
  return '';
}

// ── Audio Player ────────────────────────────────────────────────────────────
comps['audio-player'] = {
  template: '#audio-player-template',
  props: {
    item: { type: Object, required: true },
    showRename: Boolean,
    showDelete: Boolean,
    showDetail: Boolean,
    showDownload: Boolean,
    showSave: Boolean,
    primaryLabel: String,
  },
  emits: ['delete', 'rename', 'detail', 'save'],
  data() {
    return {
      playing: false,
      currentTime: 0,
      duration: 0,
      seeker: false,
      _audio: null,
    };
  },
  computed: {
    durStr() {
      return this.item.duration ? this.item.duration.toFixed(1) + 's' : '';
    },
    sizeStr() {
      if (!this.item.size) return '';
      return this.item.size > 1048576
        ? (this.item.size / 1048576).toFixed(1) + ' MB'
        : (this.item.size / 1024).toFixed(0) + ' KB';
    },
    dateStr() {
      if (!this.item.created_at) return '';
      const d = new Date(this.item.created_at * 1000);
      return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    },
    isCurrent() {
      return this.$store.currentName === this.item.name && this.playing;
    },
  },
  watch: {
    '$store.currentName'(name) {
      if (name !== this.item.name && this.playing) this.stop();
    },
  },
  unmounted() {
    this.stop();
  },
  methods: {
    formatTime(s) {
      if (!s || !isFinite(s)) return '0:00';
      const m = Math.floor(s / 60);
      const sec = Math.floor(s % 60);
      return m + ':' + (sec < 10 ? '0' : '') + sec;
    },
    togglePlay() {
      if (this._audio && this.playing) {
        this.stop();
        return;
      }
      // Stop any other playing audio
      if (this.$store.currentAudio) {
        this.$store.currentAudio.pause();
        this.$store.currentAudio = null;
        this.$store.currentName = '';
      }
      const audio = new Audio(this.item.url);
      this._audio = audio;
      this.seeker = true;
      this.playing = true;
      this.$store.currentAudio = audio;
      this.$store.currentName = this.item.name;

      audio.addEventListener('timeupdate', () => {
        this.currentTime = audio.currentTime;
        this.duration = audio.duration || 0;
      });
      audio.addEventListener('ended', () => this.stop());
      audio.play().catch(() => this.stop());
    },
    stop() {
      if (this._audio) {
        this._audio.pause();
        this._audio = null;
      }
      this.playing = false;
      this.seeker = false;
      this.currentTime = 0;
      this.duration = 0;
      if (this.$store.currentName === this.item.name) {
        this.$store.currentAudio = null;
        this.$store.currentName = '';
      }
    },
    seek(e) {
      const rect = e.currentTarget.getBoundingClientRect();
      const pct = (e.clientX - rect.left) / rect.width;
      const audio = this._audio || this.$store.currentAudio;
      if (audio && audio.duration) audio.currentTime = pct * audio.duration;
    },
  },
};

// ── Voice Panel ──────────────────────────────────────────────────────────────
comps['voice-panel'] = {
  template: '#voice-panel-template',
  data() {
    return { renaming: null };
  },
  computed: {
    items() { return this.$store.voiceDetails; },
  },
  methods: {
    startRename(name) {
      this.renaming = { original: name, current: name };
      this.$nextTick(() => {
        const el = this.$el.querySelector('.name-edit');
        if (el) { el.focus(); el.select(); }
      });
    },
    submitRename() {
      const r = this.renaming;
      if (!r) return;
      const val = r.current.trim();
      if (!val || val === r.original) { this.renaming = null; return; }
      fetch('/voice/' + encodeURIComponent(r.original) + '?new_name=' + encodeURIComponent(val), { method: 'PUT' })
        .then(r2 => r2.json())
        .then(data => {
          const v = this.$store.voiceDetails.find(v => v.name === r.original);
          if (v) { v.name = data.name; v.url = data.url; }
          const oldName = r.original;
          this.$store.models.forEach(m => {
            if (m.voices && m.voices.cloneable) {
              const idx = m.voices.cloneable.indexOf(oldName);
              if (idx >= 0) m.voices.cloneable[idx] = data.name;
            }
          });
          this.renaming = null;
        })
        .catch(() => { this.renaming = null; });
    },
    cancelRename() { this.renaming = null; },

    deleteVoice(name) {
      if (!confirm('Delete voice "' + name + '"?')) return;
      fetch('/voice/' + encodeURIComponent(name), { method: 'DELETE' })
        .then(r => {
          if (!r.ok) return;
          this.$store.voiceDetails = this.$store.voiceDetails.filter(v => v.name !== name);
          this.$store.models.forEach(m => {
            if (m.voices && m.voices.cloneable) {
              const idx = m.voices.cloneable.indexOf(name);
              if (idx >= 0) m.voices.cloneable.splice(idx, 1);
            }
          });
        });
    },
  },
};

// ── SFX Panel ────────────────────────────────────────────────────────────────
comps['sfx-panel'] = {
  template: '#sfx-panel-template',
  data() {
    return { renaming: null, uploading: false };
  },
  computed: {
    items() { return this.$store.sfxDetails || []; },
  },
  mounted() {
    this.loadSFX();
  },
  methods: {
    loadSFX() {
      fetch('/v1/sfx')
        .then(r => r.json())
        .then(data => {
          this.$store.sfxDetails = data.data || [];
          this.$store.sfx = (data.data || []).map(s => s.name);
        })
        .catch(() => {});
    },
    triggerUpload() {
      this.$refs.sfxUploadInput.click();
    },
    uploadSFXFile(event) {
      const file = event.target.files[0];
      if (!file) return;
      this.uploading = true;
      const fd = new FormData();
      fd.append('file', file);
      fetch('/sfx', { method: 'POST', body: fd })
        .then(r => r.json())
        .then(() => {
          this.loadSFX();
        })
        .catch(() => {})
        .finally(() => {
          this.uploading = false;
          event.target.value = '';
        });
    },
    startRename(name) {
      this.renaming = { original: name, current: name };
      this.$nextTick(() => {
        const el = this.$el.querySelector('.sfx-name-edit');
        if (el) { el.focus(); el.select(); }
      });
    },
    submitRename() {
      const r = this.renaming;
      if (!r) return;
      const val = r.current.trim();
      if (!val || val === r.original) { this.renaming = null; return; }
      fetch('/sfx/' + encodeURIComponent(r.original) + '?new_name=' + encodeURIComponent(val), { method: 'PUT' })
        .then(r2 => r2.json())
        .then(() => {
          this.loadSFX();
          this.renaming = null;
        })
        .catch(() => { this.renaming = null; });
    },
    cancelRename() { this.renaming = null; },
    deleteSFX(name) {
      if (!confirm('Delete SFX "' + name + '"?')) return;
      fetch('/sfx/' + encodeURIComponent(name), { method: 'DELETE' })
        .then(r => {
          if (r.ok) this.loadSFX();
        });
    }
  }
};

// ── Preset Panel ─────────────────────────────────────────────────────────────
comps['preset-panel'] = {
  template: '#preset-panel-template',
  data() {
    return { renaming: null };
  },
  computed: {
    items() { return this.$store.presets || []; },
  },
  methods: {
    startRename(name) {
      this.renaming = { original: name, current: name };
      this.$nextTick(() => {
        const el = this.$el.querySelector('.preset-name-edit');
        if (el) { el.focus(); el.select(); }
      });
    },
    submitRename() {
      const r = this.renaming;
      if (!r) return;
      const val = r.current.trim();
      if (!val || val === r.original) { this.renaming = null; return; }
      fetch('/presets/' + encodeURIComponent(r.original), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_name: val }),
      })
        .then(r2 => r2.json())
        .then(data => {
          if (data.presets) this.$store.presets = data.presets;
          this.renaming = null;
        })
        .catch(() => { this.renaming = null; });
    },
    cancelRename() { this.renaming = null; },
    deletePreset(name) {
      if (!confirm('Delete preset "' + name + '"?')) return;
      fetch('/presets/' + encodeURIComponent(name), { method: 'DELETE' })
        .then(r => r.json())
        .then(data => {
          if (data.presets) this.$store.presets = data.presets;
        });
    },
    applyPreset(preset) {
      fetch('/presets/' + encodeURIComponent(preset.name))
        .then(r => r.json())
        .then(data => {
          const cfg = data.config || {};
          const f = this.$store.form;
          if (cfg.model) f.model = cfg.model;
          if (cfg.speaker_name) f.speaker_name = cfg.speaker_name;
          if (cfg.voice_description != null) f.voice_description = cfg.voice_description;
          if (cfg.speed != null) f.speed = Math.min(4, Math.max(0.25, parseFloat(cfg.speed)));
          if (cfg.temperature != null) f.temperature = parseFloat(cfg.temperature);
          if (cfg.seed !== undefined) f.seed = cfg.seed;
          if (cfg.auto_ssml !== undefined) f.auto_ssml = !!cfg.auto_ssml;
          if (cfg.exaggeration != null) f.exaggeration = parseFloat(cfg.exaggeration);
          if (cfg.cfg_weight != null) f.cfg_weight = parseFloat(cfg.cfg_weight);
          if (cfg.blendMode !== undefined) this.$store.blendMode = !!cfg.blendMode;
          if (cfg.blendSelections) this.$store.blendSelections = { ...cfg.blendSelections };
          if (cfg.e2eEnabled !== undefined) this.$store.e2eEnabled = !!cfg.e2eEnabled;
          if (cfg.e2eModel) this.$store.e2eModel = cfg.e2eModel;
          if (cfg.e2eLanguage != null) this.$store.e2eLanguage = cfg.e2eLanguage;
        })
        .catch(() => {});
    },

    openSavePreset() {
      this.$store.showSavePreset = true;
      this.$store.savePresetStatus = '';
      this.$store.savePresetStatusClass = '';
    },
  },
};

// ── Output Panel ─────────────────────────────────────────────────────────────
comps['output-panel'] = {
  template: '#output-panel-template',
  computed: {
    hasOutputs() { return this.$store.outputs.length > 0; },
    engineOptions() {
      const s = new Set();
      this.$store.outputs.forEach(o => {
        const eng = this.$store.models.find(m => m.id === (o.params && o.params.model));
        if (eng) s.add(eng.engine);
      });
      return [...s].sort();
    },
    modelOptions() {
      const s = new Set();
      this.$store.outputs.forEach(o => {
        if (o.params && o.params.model) s.add(o.params.model);
      });
      return [...s].sort();
    },
    filtered() {
      const fs = this.$store.filterState;
      return this.$store.outputs.filter(o => {
        const eng = this.$store.models.find(m => m.id === (o.params && o.params.model));
        if (fs.engine && eng && eng.engine !== fs.engine) return false;
        if (fs.model && o.params && o.params.model !== fs.model) return false;
        if (fs.time) {
          const cutoff = Date.now() / 1000 - parseInt(fs.time) * 60;
          if ((o.created_at || 0) < cutoff) return false;
        }
        return true;
      });
    },
    displayItems() {
      const list = this.filtered;
      const groups = {};
      const individual = [];
      list.forEach(o => {
        const bid = o.params && o.params.batch_id;
        if (bid) {
          if (!groups[bid]) groups[bid] = { batchId: bid, items: [], _maxTs: 0 };
          groups[bid].items.push(o);
          if (o.created_at > groups[bid]._maxTs) groups[bid]._maxTs = o.created_at;
        } else {
          individual.push(o);
        }
      });
      const result = [];
      Object.keys(groups).forEach(k => {
        const g = groups[k];
        g.items.sort((a, b) =>
          (a.params && a.params.batch_seq != null ? a.params.batch_seq : 0) -
          (b.params && b.params.batch_seq != null ? b.params.batch_seq : 0)
        );
        const names = g.items.map(x => {
          const m = this.$store.models.find(mdl => mdl.id === (x.params && x.params.model));
          return m ? m.name : (x.params && x.params.model) || '?';
        });
        result.push({ _type: 'batch_summary', batchId: k, label: names.join(', '), items: g.items, _ts: g._maxTs });
      });
      individual.forEach(o => result.push(o));
      result.sort((a, b) => (b._ts || b.created_at || 0) - (a._ts || a.created_at || 0));
      return result;
    },
  },
  methods: {
    clearFilters() {
      this.$store.filterState = { engine: '', model: '', time: '' };
    },
    clearOutputs() {
      if (!confirm('Delete all generated outputs?')) return;
      fetch('/outputs', { method: 'DELETE' }).then(r => {
        if (!r.ok) return;
        if (this.$store.currentAudio) { this.$store.currentAudio.pause(); this.$store.currentAudio = null; this.$store.currentName = ''; }
        this.$store.outputs = [];
      });
    },
    deleteOutput(name) {
      if (!confirm('Delete "' + name + '"?')) return;
      fetch('/output/' + encodeURIComponent(name), { method: 'DELETE' }).then(r => {
        if (!r.ok) return;
        if (this.$store.currentName === name) { this.$store.currentAudio.pause(); this.$store.currentAudio = null; this.$store.currentName = ''; }
        this.$store.outputs = this.$store.outputs.filter(o => o.name !== name);
      });
    },
    showDetail(out) {
      this.$store.modalOut = out;
      this.$store.regenParams = out.params || null;
      this.$store.showParams = true;
    },
    openSaveModal(item) {
      this.$store.saveOutputItem = item;
      this.$store.saveOutputStatus = '';
      this.$store.saveOutputStatusClass = '';
      this.$store.showSaveOutput = true;
    },
    openBatchDetail(group) {
      this.$store.batchDetailItems = group.items;
      this.$store.batchDetailLabel = group.label;
      this.$store.showBatchDetail = true;
    },
    batchTotalStr(group) {
      let total = 0;
      group.items.forEach(o => { if (o.duration) total += o.duration; });
      return total.toFixed(1) + 's total';
    },
  },
};

// ── Generate Form ────────────────────────────────────────────────────────────
comps['generate-form'] = {
  template: '#generate-form-template',
  data() {
    return {
      genStatus: '',
      genStatusClass: '',
      btnState: '',
      transcribeStaging: false,
      transcribeStagingStatus: '',
      transcribeStagingStatusClass: '',
      transcribeUrlFetching: false,
      expandedFileGroups: {},
    };
  },
  computed: {
    selectedModel() {
      return this.$store.models.find(m => m.id === this.$store.form.model) || null;
    },
    capabilities() {
      return (this.selectedModel && this.selectedModel.capabilities) || [];
    },
    modelVoices() {
      const m = this.selectedModel;
      if (!m || !m.voices) return { built_in: [], cloneable: [] };
      return m.voices;
    },
    blendVoicesCount() {
      return Object.keys(this.$store.blendSelections).length;
    },
    blendVoiceString() {
      const selections = this.$store.blendSelections;
      const keys = Object.keys(selections);
      if (!keys.length) return '';
      const parts = keys.map(k => {
        const w = selections[k];
        return keys.length > 1 ? k + ':' + w.toFixed(2) : k;
      });
      return parts.join(', ');
    },
    modelEngine() {
      return (this.selectedModel && this.selectedModel.engine) || '';
    },
    modelDesc() {
      return (this.selectedModel && this.selectedModel.description) || '';
    },
    modelLangs() {
      return (this.selectedModel && this.selectedModel.languages) || [];
    },
    groupedModels() {
      const groups = {};
      this.$store.models.forEach(m => {
        if (m.capabilities.includes('text_to_music') || m.capabilities.includes('text_to_sfx') || m.engine === 'musicgen') return;
        const e = m.engine || 'other';
        if (!groups[e]) groups[e] = [];
        groups[e].push(m);
      });
      return groups;
    },
    musicModels() {
      return this.$store.models.filter(m => m.capabilities.includes('text_to_music') || m.capabilities.includes('text_to_sfx') || m.engine === 'musicgen');
    },
    selectedMusicModel() {
      return this.$store.models.find(m => m.id === this.$store.musicForm.model) || null;
    },
    musicModelDesc() {
      return (this.selectedMusicModel && this.selectedMusicModel.description) || '';
    },
    engineOrder() {
      return ['qwen', 'kokoro', 'piper', 'chatterbox'];
    },
    sortedEngines() {
      return Object.keys(this.groupedModels).sort(
        (a, b) => {
          const o = this.engineOrder;
          return (o.indexOf(a) === -1 ? 99 : o.indexOf(a)) - (o.indexOf(b) === -1 ? 99 : o.indexOf(b));
        }
      );
    },
    curlCommand() {
      if (this.$store.activeTab === 'music') {
        const m = this.$store.musicForm.model;
        const t = this.$store.musicForm.text.trim();
        if (!m || !t) return null;
        const body = {
          model: m,
          input: t,
          voice: 'default',
          duration: parseFloat(this.$store.musicForm.duration),
        };
        const json = JSON.stringify(body, null, 2);
        return [
          'curl -X POST http://localhost:8000/v1/audio/speech \\',
          '  -H "Content-Type: application/json" \\',
          '  -H "X-Save-Output: true" \\',
          "  -d '" + json.replace(/'/g, "'\\''") + "' \\",
          '  --output music.wav',
        ].join('\n');
      }
      const m = this.$store.form.model;
      const t = this.$store.form.text.trim();
      if (!m || !t) return null;
      const caps = this.capabilities;
      const body = { model: m, input: t, speed: parseFloat(this.$store.form.speed) };
      const voice = buildVoiceForCapabilities(caps, this.$store);
      if (voice) body.voice = voice;
      if (caps.includes('temperature')) {
        body.temperature = parseFloat(this.$store.form.temperature);
      }
      if (this.$store.form.seed) body.seed = parseInt(this.$store.form.seed, 10);
      if (caps.includes('emotion')) {
        body.exaggeration = parseFloat(this.$store.form.exaggeration);
        body.cfg_weight = parseFloat(this.$store.form.cfg_weight);
      }
      const json = JSON.stringify(body, null, 2);
      return [
        'curl -X POST http://localhost:8000/v1/audio/speech \\',
        '  -H "Content-Type: application/json" \\',
        '  -H "X-Save-Output: true" \\',
        '  -H "x-auto-ssml: true" \\',
        "  -d '" + json.replace(/'/g, "'\\''") + "' \\",
        '  --output speech.mp3',
      ].join('\n');
    },
    curlReady() { return !!this.curlCommand; },

    // Batch mode computed
    batchTabs() {
      const tabs = [];
      if (this.cloneModels.length) tabs.push({ key: 'clone', label: 'Voice Clone' });
      if (this.promptModels.length) tabs.push({ key: 'prompt', label: 'Voice Prompt' });
      if (this.speakerModels.length) tabs.push({ key: 'multivoice', label: 'Multi-Voice' });
      return tabs;
    },
    cloneModels() {
      return this.$store.models.filter(m => m.available && m.capabilities.includes('voice_clone'));
    },
    promptModels() {
      return this.$store.models.filter(m => m.available && m.capabilities.includes('voice_prompt'));
    },
    speakerModels() {
      return this.$store.models.filter(m => m.available && (m.capabilities.includes('speaker') || m.capabilities.includes('voice_blend')));
    },
    speakerModelsByEngine() {
      const groups = {};
      this.speakerModels.forEach(m => {
        const e = m.engine || 'other';
        if (!groups[e]) groups[e] = [];
        groups[e].push(m);
      });
      return groups;
    },
    speakerEngineNames() {
      return Object.keys(this.speakerModelsByEngine);
    },
    multivoiceVoices() {
      const m = this.$store.models.find(x => x.id === this.$store.multivoiceModel);
      return (m && m.voices && m.voices.built_in) ? m.voices.built_in : [];
    },
    multivoiceSelectedCount() {
      return this.$store.multivoiceSelectedVoices.length;
    },
    allCloneableVoices() {
      return this.$store.voiceDetails.map(v => v.name);
    },
    cloneBatchLabel() {
      const n = this.$store.selectedBatchModels.length;
      const total = this.cloneModels.length;
      return n + ' of ' + total + ' selected';
    },
    promptBatchLabel() {
      const n = this.$store.selectedBatchModels.length;
      const total = this.promptModels.length;
      return n + ' of ' + total + ' selected';
    },
    batchSubmitDisabled() {
      if (!this.$store.batchMode) return false;
      if (this.$store.batchTab === 'multivoice') {
        return !this.$store.multivoiceModel || !this.$store.multivoiceSelectedVoices.length;
      }
      return !this.$store.selectedBatchModels.length;
    },
    batchSubmitLabel() {
      if (this.$store.batchProgress) return 'Generating...';
      if (!this.$store.batchMode) return 'Generate';
      if (this.$store.batchTab === 'multivoice') {
        const n = this.$store.multivoiceSelectedVoices.length;
        return 'Generate with ' + n + ' voice' + (n === 1 ? '' : 's');
      }
      return 'Batch Generate';
    },
    hasAvailSttModel() {
      return (this.$store.e2eModels || []).some(m => m.available);
    },
    sttMlxModels() {
      return (this.$store.e2eModels || []).filter(m => m.mlx_required);
    },
    sttFasterModels() {
      return (this.$store.e2eModels || []).filter(m => !m.mlx_required);
    },
    availSttModels() {
      return (this.$store.e2eModels || []).filter(m => m.available);
    },
    activeStagedFile() {
      const files = this.$store.transcribeForm.stagedFiles;
      return files[this.$store.transcribeForm.activeFileIndex] || null;
    },
    canTranscribe() {
      if (!this.$store.transcribeForm.stagedFiles.length) return false;
      if (this.$store.batchTranscribeMode) return this.$store.selectedTranscribeModels.length > 0;
      return !!this.$store.transcribeForm.model;
    },
    selectedTranscribeCount() {
      return this.$store.selectedTranscribeModels.length;
    },
    batchTranscribeLabel() {
      if (this.$store.batchTranscribeProgress) return 'Transcribing...';
      const n = this.$store.selectedTranscribeModels.length;
      const f = this.$store.transcribeForm.stagedFiles.length;
      return 'Transcribe ' + f + ' file' + (f > 1 ? 's' : '') + ' with ' + n + ' model' + (n === 1 ? '' : 's');
    },
    batchGroupedResults() {
      const groups = {};
      this.$store.batchTranscribeResults.forEach(r => {
        if (!groups[r.fileName]) groups[r.fileName] = { fileName: r.fileName, results: [] };
        groups[r.fileName].results.push(r);
      });
      return Object.values(groups);
    },
    advancedSummary() {
      const parts = [];
      const caps = this.capabilities;
      const f = this.$store.form;
      parts.push(Number(f.speed).toFixed(2) + 'x');
      if (caps.includes('temperature')) parts.push('Temp ' + Number(f.temperature).toFixed(1));
      if (f.seed) parts.push('Seed ' + f.seed);
      if (caps.includes('emotion')) {
        parts.push('Exagg ' + Number(f.exaggeration).toFixed(2));
        parts.push('CFG ' + Number(f.cfg_weight).toFixed(2));
      }
      if (f.auto_ssml && this.$store.form.text.length >= 300) parts.push('Auto-SSML');
      if (this.$store.e2eEnabled) parts.push('STT on');
      return parts.length ? '— ' + parts.join(' · ') : '';
    },
    ssmlValidationError() {
      const text = this.$store.form.text.trim();
      if (!text.startsWith('<speak')) return null;

      try {
        const parser = new DOMParser();
        const doc = parser.parseFromString(text, 'application/xml');
        const parserError = doc.querySelector('parsererror');
        if (parserError) {
          return parserError.textContent || 'Malformed SSML syntax.';
        }
      } catch (e) {
        return e.message || 'Malformed SSML syntax.';
      }
      return null;
    },
    allModelVoices() {
      const voices = [];
      const mVoices = this.modelVoices;
      if (mVoices.built_in) voices.push(...mVoices.built_in);
      if (mVoices.cloneable) voices.push(...mVoices.cloneable);
      return voices;
    },
    allSFXFiles() {
      return this.$store.sfx || [];
    },
  },
  watch: {
    '$store.batchMode'(val) {
      if (val) {
        const tabs = this.batchTabs;
        if (tabs.length && !tabs.find(t => t.key === this.$store.batchTab)) {
          this.$store.batchTab = tabs[0].key;
        }
      }
    },
    batchTabs(tabs) {
      if (this.$store.batchMode && tabs.length && !tabs.find(t => t.key === this.$store.batchTab)) {
        this.$store.batchTab = tabs[0].key;
      }
    },
  },
  methods: {
    insertSSMLTag(tag, attrs = {}) {
      const el = document.getElementById('text');
      if (!el) return;

      const start = el.selectionStart;
      const end = el.selectionEnd;
      const text = this.$store.form.text;
      const selectedText = text.substring(start, end);

      let attrStr = '';
      for (const [k, v] of Object.entries(attrs)) {
        attrStr += ` ${k}="${v}"`;
      }

      let replacement = '';
      if (tag === 'break') {
        replacement = `<break${attrStr}/>`;
      } else if (tag === 'audio') {
        replacement = `<audio${attrStr}>${selectedText || '[SFX]'}</audio>`;
      } else if (tag === 'sub') {
        replacement = `<sub${attrStr}>${selectedText || 'WWW'}</sub>`;
      } else if (tag === 'say-as') {
        replacement = `<say-as${attrStr}>${selectedText || 'acronym'}</say-as>`;
      } else {
        replacement = `<${tag}${attrStr}>${selectedText || '...'}</${tag}>`;
      }

      this.$store.form.text = text.substring(0, start) + replacement + text.substring(end);

      this.$nextTick(() => {
        el.focus();
        const newPos = start + replacement.length;
        el.setSelectionRange(newPos, newPos);
      });
    },
    onVoiceSelect(event) {
      const voice = event.target.value;
      if (voice) {
        this.insertSSMLTag('voice', { name: voice });
        event.target.value = '';
      }
    },
    onBreakSelect(event) {
      let time = event.target.value;
      if (time === 'custom') {
        time = prompt("Enter pause duration (e.g. 500ms, 1s, 2s):", "1s");
      }
      if (time) {
        this.insertSSMLTag('break', { time: time });
      }
      event.target.value = '';
    },
    onProsodySelect(event) {
      const rate = event.target.value;
      if (rate) {
        this.insertSSMLTag('prosody', { rate: rate });
        event.target.value = '';
      }
    },
    onAudioSelect(event) {
      let src = event.target.value;
      if (src === 'custom') {
        src = prompt("Enter audio file path or URL:", "https://example.com/sound.mp3");
      }
      if (src) {
        this.insertSSMLTag('audio', { src: src });
      }
      event.target.value = '';
    },
    insertSayAsTag() {
      this.insertSSMLTag('say-as', { 'interpret-as': 'characters' });
    },
    insertSubTag() {
      this.insertSSMLTag('sub', { alias: 'substitution' });
    },
    loadSSMLTemplate() {
      this.$store.form.text = `<speak>
  <p>
    <s>Hello, welcome to Sonus.</s>
    <s>This is a demonstration of all SSML features.</s>
  </p>
  
  <break time="1s"/>
  
  <p>
    We can spell words like <say-as interpret-as="characters">SSML</say-as>,
    or substitute abbreviations like <sub alias="World Wide Web">WWW</sub>.
  </p>
  
  <break time="800ms"/>
  
  <voice name="am_adam">
    <p>
      <s>I am speaking in a different voice.</s>
      <prosody rate="1.4">And now I am speaking much faster.</prosody>
    </p>
  </voice>
  
  <break time="500ms"/>
  Narrator voice is back. Enjoy speaking freely!
</speak>`;
    },
    engineLabel(engine) {
      return engine.charAt(0).toUpperCase() + engine.slice(1);
    },
    switchBatchTab(key) {
      this.$store.batchTab = key;
      this.$store.selectedBatchModels = [];
      this.$store.multivoiceModel = '';
      this.$store.multivoiceSelectedVoices = [];
    },
    capsLabel(m) {
      if (!m.capabilities || !m.capabilities.length) return '';
      return '  [' + m.capabilities.join(', ') + ']';
    },
    unavailLabel(m) {
      return !m.available ? ' [unavailable]' : '';
    },
    onModelChange() {
      // Reset voice fields when model changes
      this.$store.form.speaker_name = '';
      this.$store.form.voice_description = '';
      this.$store.form.sample_voice_file = '';
      this.$store.form.exaggeration = 0.1;
      this.$store.form.cfg_weight = 0.0;
      this.$store.blendMode = false;
      this.$store.blendSelections = {};
    },
    isBlendSelected(v) {
      return this.$store.blendSelections[v] !== undefined;
    },
    getBlendWeight(v) {
      const w = this.$store.blendSelections[v];
      return w !== undefined ? w : 0.5;
    },
    _normalizeBlendWeights() {
      const s = this.$store.blendSelections;
      const keys = Object.keys(s);
      if (keys.length < 2) return;
      const total = keys.reduce((sum, k) => sum + s[k], 0);
      if (!total || total <= 0) return;
      const norm = {};
      keys.forEach((k, i) => {
        norm[k] = i < keys.length - 1
          ? Math.round(s[k] / total * 100) / 100
          : +(1 - keys.slice(0, -1).reduce((sum, k2) => sum + norm[k2], 0)).toFixed(2);
      });
      this.$store.blendSelections = norm;
    },
    toggleBlendVoice(v) {
      const s = { ...this.$store.blendSelections };
      if (s[v] !== undefined) {
        delete s[v];
      } else {
        s[v] = 0.5;
      }
      this.$store.blendSelections = s;
      this._normalizeBlendWeights();
    },
    setBlendWeight(v, w) {
      if (isNaN(w)) w = 0.5;
      w = Math.max(0, Math.min(1, w));
      this.$store.blendSelections = { ...this.$store.blendSelections, [v]: w };
      this._normalizeBlendWeights();
    },
    selectAllBlendVoices() {
      const obj = {};
      (this.modelVoices.built_in || []).forEach(v => { obj[v] = 0.5; });
      this.$store.blendSelections = obj;
      this._normalizeBlendWeights();
    },
    async convertToSSML() {
      const text = this.$store.form.text.trim();
      if (!text) return;
      try {
        const resp = await fetch('/v1/preview-ssml', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text }),
        });
        if (!resp.ok) throw new Error(await resp.text());
        this.$store.form.text = await resp.text();
      } catch (e) {
        this.genStatus = 'SSML conversion failed: ' + e.message;
        this.genStatusClass = 'error';
      }
    },
    stripSSML() {
      const text = this.$store.form.text.trim();
      if (!text.startsWith('<speak')) return;
      try {
        const parser = new DOMParser();
        const doc = parser.parseFromString(text, 'application/xml');
        const plain = doc.body?.textContent || doc.documentElement?.textContent || '';
        this.$store.form.text = plain.trim().replace(/\s+/g, ' ');
      } catch (e) {
        this.genStatus = 'Failed to strip SSML: ' + e.message;
        this.genStatusClass = 'error';
      }
    },
    async onSubmit() {
      const m = this.$store.form.model;
      const t = this.$store.form.text.trim();
      if (!m || !t) {
        this.genStatus = 'Please select a model and enter text.';
        this.genStatusClass = 'error';
        return;
      }
      const caps = this.capabilities;
      const body = { model: m, input: t, speed: parseFloat(this.$store.form.speed) };

      if (caps.includes('voice_blend') && this.$store.blendMode) {
        const keys = Object.keys(this.$store.blendSelections);
        if (!keys.length) {
          this.genStatus = 'Please select at least one voice for blending.';
          this.genStatusClass = 'error';
          return;
        }
      }
      const voice = buildVoiceForCapabilities(caps, this.$store);
      if (voice) body.voice = voice;
      if (caps.includes('voice_prompt') && !voice) {
        this.genStatus = 'Voice description is required.';
        this.genStatusClass = 'error';
        return;
      }
      if (caps.includes('voice_clone') && !voice) {
        this.genStatus = 'A sample voice file is required.';
        this.genStatusClass = 'error';
        return;
      }

      if (caps.includes('temperature')) {
        body.temperature = parseFloat(this.$store.form.temperature);
      }
      if (this.$store.form.seed) body.seed = parseInt(this.$store.form.seed, 10);
      if (caps.includes('emotion')) {
        body.exaggeration = parseFloat(this.$store.form.exaggeration);
        body.cfg_weight = parseFloat(this.$store.form.cfg_weight);
      }

      this.$store.loading = true;
      this.genStatus = '';
      this.genStatusClass = '';

      try {
        const resp = await fetch('/v1/audio/speech', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Save-Output': 'true',
            'x-auto-ssml': String(this.$store.form.auto_ssml),
          },
          body: JSON.stringify(body),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({ detail: 'HTTP ' + resp.status }));
          this.genStatus = err.detail || 'Error ' + resp.status;
          this.genStatusClass = 'error';
          return;
        }

        const data = await fetch('/outputs/detail').then(r => r.json());
        this.$store.outputs = data;

        if (this.$store.e2eEnabled) {
          this.genStatus = 'Transcribing...';
          this.genStatusClass = 'info';
          const sttModel = this.$store.e2eModel;
          const e2eLang = this.$store.e2eLanguage || undefined;
          for (const out of this.$store.outputs) {
            if (out.params && out.params.e2e) continue;
            const origText = out.params && out.params.input;
            if (!origText) continue;
            const plainText = origText.replace(/<[^>]+>/g, '').trim().replace(/\s+/g, ' ');
            try {
              const transResult = await this._transcribeOne(out.url, sttModel, e2eLang);
              const similarity = this._wer(plainText, transResult.text);
              const e2eData = {
                e2e: {
                  stt_model: sttModel,
                  transcription: transResult.text,
                  detected_language: transResult.detected_language || '',
                  wer: similarity.wer,
                  similarity: similarity.similarity,
                },
              };
              fetch('/output/' + encodeURIComponent(out.name) + '/meta', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(e2eData),
              }).catch(() => {});
              if (out.params) Object.assign(out.params, e2eData);
            } catch (_) {}
          }
        }

        this.btnState = 'btn-success';
        this.genStatus = 'Done!';
        this.genStatusClass = 'success';
        setTimeout(() => { this.btnState = ''; }, 1200);
      } catch (err) {
        this.btnState = 'btn-error';
        this.genStatus = 'Network error: ' + err.message;
        this.genStatusClass = 'error';
        setTimeout(() => { this.btnState = ''; }, 600);
      } finally {
        this.$store.loading = false;
      }
    },
    copyCurl() {
      if (!this.curlCommand) return;
      navigator.clipboard.writeText(this.curlCommand).then(() => {
      }).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = this.curlCommand;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      });
    },
    async _transcribeOne(url, model, lang) {
      const resp = await fetch(url);
      const blob = await resp.blob();
      const fd = new FormData();
      fd.append('file', blob, 'audio.wav');
      fd.append('model', model);
      if (lang) fd.append('language', lang);
      fd.append('response_format', 'json');
      const sttResp = await fetch('/v1/audio/transcriptions', { method: 'POST', body: fd });
      return sttResp.json();
    },
    _wer(ref, hyp) {
      const a = (ref || '').toLowerCase().split(/\s+/).filter(Boolean);
      const b = (hyp || '').toLowerCase().split(/\s+/).filter(Boolean);
      if (!a.length && !b.length) return { wer: 0, similarity: 1 };
      if (!a.length) return { wer: 1, similarity: 0 };
      const dp = Array.from({ length: a.length + 1 }, () => Array(b.length + 1).fill(0));
      for (let i = 0; i <= a.length; i++) dp[i][0] = i;
      for (let j = 0; j <= b.length; j++) dp[0][j] = j;
      for (let i = 1; i <= a.length; i++) {
        for (let j = 1; j <= b.length; j++) {
          dp[i][j] = Math.min(
            dp[i - 1][j] + 1,
            dp[i][j - 1] + 1,
            dp[i - 1][j - 1] + (a[i - 1] !== b[j - 1] ? 1 : 0),
          );
        }
      }
      const wer = a.length ? dp[a.length][b.length] / a.length : 0;
      return { wer: Math.min(wer, 1), similarity: Math.max(0, 1 - wer) };
    },

    async batchSubmit() {
      const text = this.$store.form.text.trim();
      if (!text) {
        this.genStatus = 'Please enter text.';
        this.genStatusClass = 'error';
        return;
      }

      const tab = this.$store.batchTab;
      const batchId = Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

      let items = [];
      if (tab === 'multivoice') {
        items = this.$store.multivoiceSelectedVoices.map(v => ({
          id: v,
          label: v,
          modelId: this.$store.multivoiceModel,
          voice: v,
        }));
      } else {
        const models = this.$store.selectedBatchModels;
        if (!models.length) {
          this.genStatus = 'Please select at least one model.';
          this.genStatusClass = 'error';
          return;
        }
        const voiceField = tab === 'clone' ? this.$store.form.sample_voice_file.trim() : this.$store.form.voice_description.trim();
        if (!voiceField) {
          this.genStatus = tab === 'clone' ? 'Please select a voice file.' : 'Please enter a voice description.';
          this.genStatusClass = 'error';
          return;
        }
        items = models.map(id => {
          const m = this.$store.models.find(x => x.id === id);
          return { id, label: m ? m.name : id, modelId: id, voice: voiceField };
        });
      }

      const total = items.length;
      this.$store.loading = true;
      this.$store.batchProgress = { current: 0, total, modelName: '' };
      this.$store.batchAbort = false;
      this.$store.batchSummary = null;

      let succeeded = 0;
      let failed = 0;
      const details = [];

      for (let i = 0; i < total; i++) {
        if (this.$store.batchAbort) {
          details.push('Cancelled after ' + i + ' of ' + total);
          break;
        }
        const item = items[i];
        this.$store.batchProgress = { current: i + 1, total, modelName: item.label };

        const body = {
          model: item.modelId,
          input: text,
          voice: item.voice,
          speed: parseFloat(this.$store.form.speed),
          temperature: parseFloat(this.$store.form.temperature),
        };
        if (this.$store.form.seed) body.seed = parseInt(this.$store.form.seed, 10);

        try {
          const resp = await fetch('/v1/audio/speech', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-Save-Output': 'true',
              'X-Batch-Id': batchId,
              'X-Batch-Seq': String(i),
              'x-auto-ssml': String(this.$store.form.auto_ssml),
            },
            body: JSON.stringify(body),
          });
          if (resp.ok) {
            succeeded++;
            details.push(item.label + ': done');
          } else {
            const err = await resp.json().catch(() => ({ detail: 'HTTP ' + resp.status }));
            failed++;
            details.push(item.label + ': ' + (err.detail || 'error'));
          }
        } catch (err) {
          failed++;
          details.push(item.label + ': network error');
        }

        if (i < total - 1 && !this.$store.batchAbort) {
          await new Promise(r => setTimeout(r, this.$store.batchGapMs));
        }
      }

      this.$store.batchProgress = null;
      this.$store.loading = false;

      try {
        const data = await fetch('/outputs/detail').then(r => r.json());
        this.$store.outputs = data;
      } catch {}

      if (this.$store.e2eEnabled) {
        const sttModel = this.$store.e2eModel;
        const e2eLang = this.$store.e2eLanguage || undefined;
        for (const out of this.$store.outputs) {
          if (out.params && out.params.e2e) continue;
          if (out.params && out.params.batch_id !== batchId) continue;
          const origText = out.params && out.params.input;
          if (!origText) continue;
          const plainText = origText.replace(/<[^>]+>/g, '').trim().replace(/\s+/g, ' ');
          try {
            const transResult = await this._transcribeOne(out.url, sttModel, e2eLang);
            const similarity = this._wer(plainText, transResult.text);
            const e2eData = {
              e2e: {
                stt_model: sttModel,
                transcription: transResult.text,
                detected_language: transResult.detected_language || '',
                wer: similarity.wer,
                similarity: similarity.similarity,
              },
            };
            fetch('/output/' + encodeURIComponent(out.name) + '/meta', {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(e2eData),
            }).catch(() => {});
            if (out.params) Object.assign(out.params, e2eData);
          } catch (_) {}
        }
      }

      if (this.$store.batchAbort) {
        this.$store.batchSummary = { type: 'warning', message: 'Cancelled. ' + succeeded + ' generated, ' + failed + ' failed.', detail: details.join('\n') };
      } else {
        const totalDone = succeeded + failed;
        const msg = 'Generated ' + succeeded + ' of ' + totalDone + (totalDone === 1 ? ' item' : ' items');
        const type = failed === 0 ? 'success' : 'warning';
        const extra = failed ? [failed + ' failed'] : [];
        this.$store.batchSummary = {
          type,
          message: msg + (extra.length ? ' (' + extra.join(', ') + ')' : ''),
          detail: details.join('\n'),
        };
      }

      setTimeout(() => { this.$store.batchSummary = null; }, 15000);
    },

    cancelBatch() {
      this.$store.batchAbort = true;
    },

    toggleBatchModel(id) {
      const idx = this.$store.selectedBatchModels.indexOf(id);
      if (idx >= 0) {
        this.$store.selectedBatchModels.splice(idx, 1);
      } else {
        this.$store.selectedBatchModels.push(id);
      }
    },

    selectAllVisible() {
      const tab = this.$store.batchTab;
      const models = tab === 'clone' ? this.cloneModels : this.promptModels;
      this.$store.selectedBatchModels.splice(0, this.$store.selectedBatchModels.length, ...models.map(m => m.id));
    },

    clearSelected() {
      this.$store.selectedBatchModels = [];
    },

    toggleMultivoiceVoice(name) {
      const idx = this.$store.multivoiceSelectedVoices.indexOf(name);
      if (idx >= 0) {
        this.$store.multivoiceSelectedVoices.splice(idx, 1);
      } else {
        this.$store.multivoiceSelectedVoices.push(name);
      }
    },

    selectAllVoices() {
      this.$store.multivoiceSelectedVoices.splice(0, this.$store.multivoiceSelectedVoices.length, ...this.multivoiceVoices);
    },

    // ── Music / SFX tab ───────────────────────────────────────────────────

    switchToMusicTab() {
      this.$store.activeTab = 'music';
      if (!this.$store.musicForm.model) {
        const avail = this.musicModels;
        const small = avail.find(m => m.id === 'musicgen-small');
        if (small && small.available) this.$store.musicForm.model = small.id;
        else {
          const firstAvail = avail.find(m => m.available);
          if (firstAvail) this.$store.musicForm.model = firstAvail.id;
        }
      }
    },
    async onMusicSubmit() {
      const m = this.$store.musicForm.model;
      const t = this.$store.musicForm.text.trim();
      if (!m || !t) {
        this.genStatus = 'Please select a model and enter prompt.';
        this.genStatusClass = 'error';
        return;
      }
      
      const body = {
        model: m,
        input: t,
        voice: 'default',
        duration: parseFloat(this.$store.musicForm.duration),
      };

      this.$store.loading = true;
      this.genStatus = '';
      this.genStatusClass = '';

      try {
        const resp = await fetch('/v1/audio/speech', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Save-Output': 'true',
          },
          body: JSON.stringify(body),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({ detail: 'HTTP ' + resp.status }));
          this.genStatus = err.detail || 'Error ' + resp.status;
          this.genStatusClass = 'error';
          return;
        }

        const data = await fetch('/outputs/detail').then(r => r.json());
        this.$store.outputs = data;

        this.btnState = 'btn-success';
        this.genStatus = 'Done!';
        this.genStatusClass = 'success';
        setTimeout(() => { this.btnState = ''; }, 1200);
      } catch (err) {
        this.btnState = 'btn-error';
        this.genStatus = 'Network error: ' + err.message;
        this.genStatusClass = 'error';
        setTimeout(() => { this.btnState = ''; }, 600);
      } finally {
        this.$store.loading = false;
      }
    },

    // ── Transcribe tab ────────────────────────────────────────────────────

    switchToTranscribeTab() {
      this.$store.activeTab = 'transcribe';
      if (!this.$store.transcribeForm.model) {
        const avail = this.availSttModels;
        const mlx = avail.find(m => m.mlx_required);
        if (mlx) this.$store.transcribeForm.model = mlx.id;
        else if (avail.length) this.$store.transcribeForm.model = avail[0].id;
      }
    },
    switchTranscribeMode(val) {
      this.$store.batchTranscribeMode = val;
      if (val && !this.$store.selectedTranscribeModels.length) {
        this.$store.selectedTranscribeModels = this.availSttModels.filter(m => m.available).map(m => m.id);
      }
    },

    // ── Audio staging ────────────────────────────────────────────────────

    async transcribeUploadSubmit(e) {
      const files = e.target.files;
      if (!files || !files.length) return;
      this.transcribeStaging = true;
      this.transcribeStagingStatus = 'Uploading ' + files.length + ' file(s)...';
      this.transcribeStagingStatusClass = '';
      let uploaded = 0;
      for (const file of files) {
        try {
          const fd = new FormData();
          fd.append('file', file);
          const resp = await fetch('/voice/stage', { method: 'POST', body: fd });
          const data = await resp.json();
          if (resp.ok) {
            this.$store.transcribeForm.stagedFiles.push(data);
            this.$store.transcribeForm.activeFileIndex = this.$store.transcribeForm.stagedFiles.length - 1;
            uploaded++;
          }
        } catch {}
      }
      // Clear all file inputs
      this.$el.querySelectorAll('input[type=file]').forEach(el => el.value = '');
      this.transcribeStaging = false;
      if (uploaded) this.transcribeStagingStatus = '';
      else this.transcribeStagingStatus = 'Upload failed. Check file format and try again.';
    },

    async transcribeUrlSubmit() {
      const url = this.$store.transcribeForm.urlAddress.trim();
      if (!url) { this.transcribeStagingStatus = 'Please enter a URL.'; this.transcribeStagingStatusClass = 'error'; return; }
      if (!/^https?:\/\//i.test(url)) { this.transcribeStagingStatus = 'URL must start with http:// or https://'; this.transcribeStagingStatusClass = 'error'; return; }
      this.transcribeUrlFetching = true;
      this.transcribeStagingStatus = '';
      try {
        const resp = await fetch('/voice/stage/url', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url }),
        });
        const data = await resp.json();
        if (!resp.ok) { this.transcribeStagingStatus = data.detail || 'Error ' + resp.status; this.transcribeStagingStatusClass = 'error'; return; }
        this.$store.transcribeForm.stagedFiles.push(data);
        this.$store.transcribeForm.activeFileIndex = this.$store.transcribeForm.stagedFiles.length - 1;
        this.$store.transcribeForm.urlAddress = '';
      } catch (err) { this.transcribeStagingStatus = 'Network error: ' + err.message; this.transcribeStagingStatusClass = 'error'; }
      finally { this.transcribeUrlFetching = false; }
    },

    switchActiveFile(i) {
      this.stopTranscribePlayer();
      this.$store.transcribeForm.activeFileIndex = i;
    },

    async removeStagedFile(i) {
      const file = this.$store.transcribeForm.stagedFiles[i];
      if (file) { try { await fetch('/voice/stage/' + encodeURIComponent(file.name), { method: 'DELETE' }); } catch {} }
      this.stopTranscribePlayer();
      this.$store.transcribeForm.stagedFiles.splice(i, 1);
      if (!this.$store.transcribeForm.stagedFiles.length) {
        this.$store.transcribeForm.audioSource = 'file';
      } else if (this.$store.transcribeForm.activeFileIndex >= this.$store.transcribeForm.stagedFiles.length) {
        this.$store.transcribeForm.activeFileIndex = this.$store.transcribeForm.stagedFiles.length - 1;
      }
    },

    addMoreFiles() {
      this.$store.transcribeForm.audioSource = 'file';
      this.$el.querySelector('#transcribeFileAddInput')?.click();
    },

    // ── Recording ────────────────────────────────────────────────────────

    generateTranscribeVoiceName() {
      const adj = ['Velvet','Crimson','Amber','Azure','Neon','Shadow','Crystal','Silver','Midnight','Solar','Ember','Frost','Echo','Prism','Nova','Aurora','Drift','Pulse'];
      const noun = ['Voice','Audio','Clip','Sample','Track','Wave','Take','Feed','Stream','Segment','Record','Chunk'];
      return adj[Math.floor(Math.random() * adj.length)] + '_' + noun[Math.floor(Math.random() * noun.length)];
    },

    async startTranscribeRecording() {
      if (!this.$store.transcribeForm.recordName.trim()) {
        this.$store.transcribeForm.recordName = this.generateTranscribeVoiceName();
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        this.transcribeStagingStatus = window.isSecureContext === false
          ? 'Recording requires HTTPS / localhost. Use http://localhost:8000.'
          : 'Recording not supported in this browser.';
        this.transcribeStagingStatusClass = 'error';
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        this.$store.transcribeStream = stream;
        this.$store.transcribeChunks = [];
        this.$store.transcribeRecorder = new MediaRecorder(stream, {
          mimeType: MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm',
        });
        this.$store.transcribeRecorder.ondataavailable = (e => { if (e.data.size > 0) this.$store.transcribeChunks.push(e.data); });
        this.$store.transcribeRecorder.onstop = () => this.onTranscribeRecordingStop();
        this.$store.transcribeRecorder.start();
        this.$store.transcribeRecording = true;
        this.transcribeStagingStatus = 'Recording... Speak now.';
        this.transcribeStagingStatusClass = 'success';

        this.$store.transcribeCtx = new AudioContext();
        const src = this.$store.transcribeCtx.createMediaStreamSource(stream);
        this.$store.transcribeAnalyser = this.$store.transcribeCtx.createAnalyser();
        this.$store.transcribeAnalyser.fftSize = 128;
        src.connect(this.$store.transcribeAnalyser);
        this.drawTranscribeWave();
      } catch (err) {
        this.transcribeStagingStatus = 'Microphone access denied: ' + err.message;
        this.transcribeStagingStatusClass = 'error';
      }
    },

    stopTranscribeRecording() {
      if (this.$store.transcribeRecorder && this.$store.transcribeRecorder.state !== 'inactive') this.$store.transcribeRecorder.stop();
      this.$store.transcribeRecording = false;
    },

    async onTranscribeRecordingStop() {
      if (this.$store.transcribeStream) { this.$store.transcribeStream.getTracks().forEach(t => t.stop()); this.$store.transcribeStream = null; }
      if (this.$store.transcribeAnimFrame) { cancelAnimationFrame(this.$store.transcribeAnimFrame); this.$store.transcribeAnimFrame = null; }
      this.$store.transcribeAnalyser = null;
      if (this.$store.transcribeCtx) { this.$store.transcribeCtx.close(); this.$store.transcribeCtx = null; }
      this.$store.transcribeRecording = false;
      if (!this.$store.transcribeChunks.length) return;

      const blob = new Blob(this.$store.transcribeChunks, { type: this.$store.transcribeRecorder ? this.$store.transcribeRecorder.mimeType : 'audio/webm' });
      const fd = new FormData();
      fd.append('file', blob, this.$store.transcribeForm.recordName.trim() + '.webm');
      fd.append('name', this.$store.transcribeForm.recordName.trim());
      this.transcribeStagingStatus = 'Uploading...';
      this.transcribeStagingStatusClass = '';
      try {
        const resp = await fetch('/voice/stage', { method: 'POST', body: fd });
        const data = await resp.json();
        if (!resp.ok) { this.transcribeStagingStatus = data.detail || 'Error ' + resp.status; this.transcribeStagingStatusClass = 'error'; return; }
        this.$store.transcribeForm.stagedFiles.push(data);
        this.$store.transcribeForm.activeFileIndex = this.$store.transcribeForm.stagedFiles.length - 1;
        this.$store.transcribeForm.recordName = '';
        this.transcribeStagingStatus = '';
      } catch (err) { this.transcribeStagingStatus = 'Network error: ' + err.message; this.transcribeStagingStatusClass = 'error'; }
    },

    drawTranscribeWave() {
      if (!this.$store.transcribeAnalyser) return;
      const canvas = this.$el && this.$el.querySelector('#transcribe-wave');
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      const bufferLength = this.$store.transcribeAnalyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);
      const w = canvas.width, h = canvas.height;
      const draw = () => {
        if (!this.$store.transcribeAnalyser) return;
        this.$store.transcribeAnimFrame = requestAnimationFrame(draw);
        this.$store.transcribeAnalyser.getByteTimeDomainData(dataArray);
        ctx.fillStyle = '#0d1117';
        ctx.fillRect(0, 0, w, h);
        ctx.lineWidth = 2;
        ctx.strokeStyle = '#58a6ff';
        ctx.beginPath();
        const sliceWidth = w / bufferLength;
        let x = 0;
        for (let i = 0; i < bufferLength; i++) {
          const v = dataArray[i] / 128.0;
          const y = v * h / 2;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
          x += sliceWidth;
        }
        ctx.lineTo(w, h / 2);
        ctx.stroke();
      };
      draw();
    },

    // ── Staged audio player ──────────────────────────────────────────────

    formatTranscribeTime(s) {
      if (!s || !isFinite(s)) return '0:00';
      const m = Math.floor(s / 60);
      const sec = Math.floor(s % 60);
      return m + ':' + (sec < 10 ? '0' : '') + sec;
    },

    toggleTranscribePlayer() {
      if (this.$store.transcribeAudioEl && this.$store.transcribePlaying) {
        this.stopTranscribePlayer();
        return;
      }
      if (this.$store.currentAudio) { this.$store.currentAudio.pause(); this.$store.currentAudio = null; this.$store.currentName = ''; }
      if (this.$store.transcribeAudioEl) { this.$store.transcribeAudioEl.pause(); this.$store.transcribeAudioEl = null; }
      const s = this.activeStagedFile;
      if (!s) return;
      const audio = new Audio(s.url);
      this.$store.transcribeAudioEl = audio;
      this.$store.transcribeSeeker = true;
      this.$store.transcribePlaying = true;

      audio.addEventListener('timeupdate', () => {
        this.$store.transcribeCurrentTime = audio.currentTime;
        this.$store.transcribeDuration = audio.duration || 0;
      });
      audio.addEventListener('ended', () => this.stopTranscribePlayer());
      audio.play().catch(() => this.stopTranscribePlayer());
    },

    stopTranscribePlayer() {
      if (this.$store.transcribeAudioEl) { this.$store.transcribeAudioEl.pause(); this.$store.transcribeAudioEl = null; }
      this.$store.transcribePlaying = false;
      this.$store.transcribeSeeker = false;
      this.$store.transcribeCurrentTime = 0;
      this.$store.transcribeDuration = 0;
    },

    seekTranscribePlayer(e) {
      const rect = e.currentTarget.getBoundingClientRect();
      const pct = (e.clientX - rect.left) / rect.width;
      const audio = this.$store.transcribeAudioEl;
      if (audio && audio.duration) audio.currentTime = pct * audio.duration;
    },

    // ── Transcription core ────────────────────────────────────────────────

    async submitTranscribe() {
      const files = this.$store.transcribeForm.stagedFiles;
      const model = this.$store.transcribeForm.model;
      if (!files.length || !model) {
        this.$store.transcribeStatus = 'Please upload audio and select a model.';
        this.$store.transcribeStatusClass = 'error';
        return;
      }
      this.$store.transcribeLoading = true;
      this.$store.transcribeStatus = 'Transcribing ' + files.length + ' file(s)...';
      this.$store.transcribeStatusClass = '';
      this.$store.transcribeResults = [];
      const lang = this.$store.transcribeForm.language.trim() || undefined;

      for (const file of files) {
        try {
          const audioResp = await fetch(file.url);
          const blob = await audioResp.blob();
          const fd = new FormData();
          fd.append('file', blob, file.name);
          fd.append('model', model);
          if (lang) fd.append('language', lang);
          fd.append('response_format', 'verbose_json');
          const resp = await fetch('/v1/audio/transcriptions', {
            method: 'POST',
            headers: { 'x-save-output': 'true' },
            body: fd,
          });
          const data = await resp.json();
          if (resp.ok) {
            this.$store.transcribeResults.push({
              fileName: file.name.replace('.wav', ''),
              text: data.text,
              detected_language: data.detected_language || '',
            });
          } else {
            this.$store.transcribeResults.push({
              fileName: file.name.replace('.wav', ''),
              text: '[Error: ' + (data.detail || resp.status) + ']',
              detected_language: '',
              error: true,
            });
          }
        } catch (err) {
          this.$store.transcribeResults.push({
            fileName: file.name.replace('.wav', ''),
            text: '[Network error]',
            detected_language: '',
            error: true,
          });
        }
      }

      this.$store.transcribeLoading = false;
      this.$store.transcribeStatus = '';
      try { const out = await fetch('/outputs/detail').then(r => r.json()); this.$store.outputs = out; } catch {}
    },

    async submitBatchTranscribe() {
      const files = this.$store.transcribeForm.stagedFiles;
      const models = this.$store.selectedTranscribeModels;
      if (!files.length || !models.length) {
        this.$store.transcribeStatus = 'Please upload audio and select at least one model.';
        this.$store.transcribeStatusClass = 'error';
        return;
      }
      const lang = this.$store.transcribeForm.language.trim() || undefined;

      this.$store.batchTranscribeAbort = false;
      this.$store.batchTranscribeResults = [];
      this.$store.batchTranscribeSummary = null;
      const total = files.length * models.length;
      this.$store.batchTranscribeProgress = { current: 0, total, modelName: '' };
      this.$store.transcribeStatus = '';
      this.expandedFileGroups = {};

      let succeeded = 0;
      let failed = 0;
      let done = 0;
      const errors = [];

      for (const file of files) {
        for (const modelId of models) {
          if (this.$store.batchTranscribeAbort) { errors.push('Cancelled after ' + done + ' of ' + total); break; }
          const m = this.$store.e2eModels.find(x => x.id === modelId);
          const label = m ? m.name : modelId;
          done++;
          this.$store.batchTranscribeProgress = { current: done, total, modelName: file.name.replace('.wav', '') + ' / ' + label };

          try {
            const audioResp = await fetch(file.url);
            const blob = await audioResp.blob();
            const fd = new FormData();
            fd.append('file', blob, file.name);
            fd.append('model', modelId);
            if (lang) fd.append('language', lang);
            fd.append('response_format', 'verbose_json');
            const resp = await fetch('/v1/audio/transcriptions', {
              method: 'POST',
              headers: { 'x-save-output': 'true' },
              body: fd,
            });
            const data = await resp.json();
            if (resp.ok) {
              this.$store.batchTranscribeResults.push({
                fileName: file.name.replace('.wav', ''),
                modelId,
                modelName: label,
                text: data.text,
                detected_language: data.detected_language || '',
              });
              succeeded++;
            } else {
              this.$store.batchTranscribeResults.push({
                fileName: file.name.replace('.wav', ''),
                modelId,
                modelName: label,
                text: '[Error: ' + (data.detail || resp.status) + ']',
                detected_language: '',
                error: true,
              });
              failed++;
            }
          } catch (err) {
            this.$store.batchTranscribeResults.push({
              fileName: file.name.replace('.wav', ''),
              modelId,
              modelName: label,
              text: '[Network error]',
              detected_language: '',
              error: true,
            });
            failed++;
          }
        }
        if (this.$store.batchTranscribeAbort) break;
      }

      this.$store.batchTranscribeProgress = null;
      try { const out = await fetch('/outputs/detail').then(r => r.json()); this.$store.outputs = out; } catch {}

      if (this.$store.batchTranscribeAbort) {
        this.$store.batchTranscribeSummary = { type: 'warning', message: 'Cancelled. ' + succeeded + ' ok, ' + failed + ' failed.', detail: errors.join('\n') };
      } else {
        this.$store.batchTranscribeSummary = {
          type: failed === 0 ? 'success' : 'warning',
          message: 'Transcribed ' + succeeded + ' of ' + (succeeded + failed) + (failed ? ' (' + failed + ' failed)' : ''),
          detail: errors.join('\n'),
        };
      }
      setTimeout(() => { this.$store.batchTranscribeSummary = null; }, 15000);
    },

    toggleFileGroup(gi) {
      const cur = this.expandedFileGroups[gi];
      this.expandedFileGroups = { ...this.expandedFileGroups, [gi]: !cur };
    },

    cancelBatchTranscribe() {
      this.$store.batchTranscribeAbort = true;
    },

    toggleTranscribeBatchModel(id) {
      const idx = this.$store.selectedTranscribeModels.indexOf(id);
      if (idx >= 0) { this.$store.selectedTranscribeModels.splice(idx, 1); }
      else { this.$store.selectedTranscribeModels.push(id); }
    },

    selectAllTranscribeModels() {
      this.$store.selectedTranscribeModels.splice(0, this.$store.selectedTranscribeModels.length, ...this.availSttModels.filter(m => m.available).map(m => m.id));
    },

    copyTranscription(text) {
      navigator.clipboard.writeText(text).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      });
    },

    downloadTranscriptionTxt(text, suffix) {
      const name = suffix || 'transcription';
      const safe = name.replace(/[^a-zA-Z0-9_-]/g, '_');
      const blob = new Blob([text], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = safe + '.txt';
      a.click();
      URL.revokeObjectURL(url);
    },
  },
};

// ── Save Preset Modal ────────────────────────────────────────────────────
comps['save-preset-modal'] = {
  template: '#save-preset-modal-template',
  data() {
    return { presetName: '', saving: false };
  },
  computed: {
    status() { return this.$store.savePresetStatus; },
    statusClass() { return this.$store.savePresetStatusClass; },
    preview() {
      const s = this.$store;
      const parts = [];
      const f = s.form;
      if (f.model) parts.push('Model: ' + f.model);
      if (s.blendMode && Object.keys(s.blendSelections).length) {
        const sel = s.blendSelections;
        parts.push('Blend: ' + Object.keys(sel).map(k => k + ':' + sel[k].toFixed(2)).join(', '));
      } else if (f.speaker_name) {
        parts.push('Voice: ' + f.speaker_name);
      }
      if (f.voice_description) parts.push('Prompt: "' + f.voice_description.slice(0, 50) + '"');
      return parts.join(' | ') || '(current form state)';
    },
  },
  mounted() {
    this.$nextTick(() => {
      const inp = this.$el.querySelector('#save-preset-name');
      if (inp) inp.focus();
    });
  },
  methods: {
    save() {
      if (this.saving) return;
      this.saving = true;
      const s = this.$store;
      const config = {
        model: s.form.model,
        speaker_name: s.form.speaker_name,
        voice_description: s.form.voice_description,
        speed: s.form.speed,
        temperature: s.form.temperature,
        seed: s.form.seed,
        auto_ssml: s.form.auto_ssml,
        exaggeration: s.form.exaggeration,
        cfg_weight: s.form.cfg_weight,
        blendMode: s.blendMode,
        blendSelections: { ...s.blendSelections },
        e2eEnabled: s.e2eEnabled,
        e2eModel: s.e2eModel,
        e2eLanguage: s.e2eLanguage,
      };
      fetch('/presets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: this.presetName.trim(), config }),
      })
        .then(r => r.json())
        .then(data => {
          if (data.name) {
            this.$store.savePresetStatus = 'Saved as "' + data.name + '"';
            this.$store.savePresetStatusClass = 'success';
            if (data.presets) this.$store.presets = data.presets;
            this.saving = false;
            setTimeout(() => this.close(), 1200);
          }
        })
        .catch(err => {
          this.$store.savePresetStatus = 'Error saving preset';
          this.$store.savePresetStatusClass = 'error';
          this.saving = false;
        });
    },
    close() { this.$store.showSavePreset = false; },
  },
};

comps['confirm-reset-modal'] = {
  template: '#confirm-reset-modal-template',
  data() {
    return {
      resetting: false,
      status: '',
      statusClass: '',
      counts: {
        outputs: this.$store.outputs.length,
        voices: this.$store.voiceDetails.length,
        presets: this.$store.presets.length,
      },
    };
  },
  methods: {
    async reset() {
      this.resetting = true;
      this.status = '';
      try {
        await fetch('/outputs', { method: 'DELETE' });
        await fetch('/v1/models/unload?all=true', { method: 'POST' }).catch(() => {});
        const voicePromises = this.$store.voiceDetails.map(v =>
          fetch('/voice/' + encodeURIComponent(v.name), { method: 'DELETE' }).catch(() => {})
        );
        const presetPromises = this.$store.presets.map(p =>
          fetch('/presets/' + encodeURIComponent(p.name), { method: 'DELETE' }).catch(() => {})
        );
        await Promise.all([...voicePromises, ...presetPromises]);
        this.$store.outputs = [];
        this.$store.voiceDetails = [];
        this.$store.voices = {};
        this.$store.presets = [];
        this.$store.filterState = { engine: '', model: '', time: '' };
        Object.assign(this.$store.form, {
          model: '',
          text: '',
          speaker_name: '',
          voice_description: '',
          sample_voice_file: '',
          speed: 1.0,
          temperature: 0,
          seed: null,
          auto_ssml: true,
          exaggeration: 0.1,
          cfg_weight: 0.0,
        });
        try { localStorage.removeItem('sonus-form'); } catch {}
        try { localStorage.removeItem('sonus-e2e'); } catch {}
        this.status = 'Reset complete.';
        this.statusClass = 'success';
        setTimeout(() => this.close(), 1500);
      } catch (err) {
        this.status = 'Error: ' + err.message;
        this.statusClass = 'error';
      } finally {
        this.resetting = false;
      }
    },
    close() { this.$store.showResetConfirm = false; },
  },
};

comps['save-output-modal'] = {
  template: '#save-output-modal-template',
  data() {
    return {
      saveName: '',
      saving: false,
    };
  },
  computed: {
    item() { return this.$store.saveOutputItem; },
    status() { return this.$store.saveOutputStatus; },
    statusClass() { return this.$store.saveOutputStatusClass; },
    canSaveAsVoice() {
      if (!this.item || !this.item.params || !this.item.params.model) return false;
      const m = this.$store.models.find(mdl => mdl.id === this.item.params.model);
      return !(m && (m.capabilities || []).some(c => c === 'text_to_music' || c === 'text_to_sfx'));
    },
  },
  mounted() {
    if (this.item) {
      this.saveName = this.item.name.replace(/\.\w+$/, '');
    }
    this.$nextTick(() => {
      const inp = this.$el.querySelector('#save-output-name');
      if (inp) inp.focus();
    });
  },
  methods: {
    close() { this.$store.showSaveOutput = false; },
    async _fetchWithTimeout(url, ms = 30000) {
      const controller = new AbortController();
      const id = setTimeout(() => controller.abort(), ms);
      try {
        return await fetch(url, { signal: controller.signal });
      } finally {
        clearTimeout(id);
      }
    },
    _setStatus(msg, cls = '') {
      this.$store.saveOutputStatus = msg;
      this.$store.saveOutputStatusClass = cls;
    },
    async saveAsVoice() {
      const name = this.saveName.trim();
      if (!name) { this._setStatus('Please enter a name.', 'error'); return; }
      const item = this.item;
      if (!item) return;
      this.saving = true;
      try {
        this._setStatus('Downloading output audio…');
        const blob = await this._fetchWithTimeout(item.url).then(r => { if (!r.ok) throw new Error('Failed to fetch output'); return r.blob(); });

        this._setStatus('Uploading to staging area…');
        const fd = new FormData();
        fd.append('file', blob, item.name);
        fd.append('name', name);
        const stage = await this._fetchWithTimeout('/voice/stage', 60000).then(r => {
          if (!r.ok) throw new Error(r.status === 409 ? 'Voice "' + name + '.wav" already exists' : 'Upload failed');
          return r.json();
        });

        this._setStatus('Saving as custom voice…');
        await this._fetchWithTimeout('/voice/stage/' + encodeURIComponent(stage.name) + '/save').then(r => {
          if (!r.ok) throw new Error('Failed to finalize voice');
        });

        this._setStatus('Refreshing voice list…');
        await fetch('/v1/voices').then(r => r.json()).then(d => {
          if (d && d.data) { applyVoiceData(this.$store, d.data); }
        }).catch(() => {});

        this._setStatus('Saved as custom voice!', 'success');
        setTimeout(() => this.close(), 1200);
      } catch (e) {
        this._setStatus(e.name === 'AbortError' ? 'Request timed out — try a shorter file' : e.message, 'error');
      } finally {
        this.saving = false;
      }
    },
    async saveAsSfx() {
      const name = this.saveName.trim();
      if (!name) { this._setStatus('Please enter a name.', 'error'); return; }
      const item = this.item;
      if (!item) return;
      this.saving = true;
      try {
        this._setStatus('Downloading output audio…');
        const blob = await this._fetchWithTimeout(item.url).then(r => { if (!r.ok) throw new Error('Failed to fetch output'); return r.blob(); });

        this._setStatus('Uploading as SFX…');
        const fd = new FormData();
        fd.append('file', blob, item.name);
        fd.append('name', name);
        const res = await this._fetchWithTimeout('/sfx', 60000).then(r => {
          if (!r.ok) throw new Error(r.status === 409 ? 'SFX "' + name + '.wav" already exists' : 'Upload failed');
          return r.json();
        });

        this.$store.sfxDetails.unshift(res);
        this.$store.sfx.push(res.name);

        this._setStatus('Saved as SFX!', 'success');
        setTimeout(() => this.close(), 1200);
      } catch (e) {
        this._setStatus(e.name === 'AbortError' ? 'Request timed out — try a shorter file' : e.message, 'error');
      } finally {
        this.saving = false;
      }
    },
  },
};

comps['curl-console'] = {
  template: '#curl-console-template',
  computed: {
    curlText() {
      const store = this.$store;

      // Batch mode — not applicable (check per-tab to avoid stale flags)
      if (
        (store.activeTab === 'generate' && store.batchMode) ||
        (store.activeTab === 'transcribe' && store.batchTranscribeMode)
      ) {
        return '# Batch mode active — curl not available for batch operations';
      }

      // Transcribe tab
      if (store.activeTab === 'transcribe') {
        const model = store.transcribeForm.model;
        const files = store.transcribeForm.stagedFiles;
        const idx = store.transcribeForm.activeFileIndex;
        const file = files.length ? files[idx] : null;
        if (!model || !file) return '# Fill out the transcribe form to generate a curl command...';
        const lines = [
          'curl -X POST http://localhost:8000/v1/audio/transcriptions \\',
          '  -H "X-Save-Output: true" \\',
          `  -F "file=@${file.name}" \\`,
          `  -F "model=${model}" \\`,
        ];
        const lang = store.transcribeForm.language.trim();
        if (lang) lines.push(`  -F "language=${lang}" \\`);
        lines.push('  -F "response_format=verbose_json"');
        return lines.join('\n');
      }

      // Generate tab
      const m = store.form.model;
      const t = store.form.text.trim();
      if (!m || !t) return '# Fill out the form to generate a curl command...';

      const model = store.models.find(x => x.id === m);
      const caps = model ? (model.capabilities || []) : [];
      const body = { model: m, input: t, speed: parseFloat(store.form.speed) };

      const voice = buildVoiceForCapabilities(caps, store);
      if (voice) body.voice = voice;

      if (caps.includes('temperature')) {
        body.temperature = parseFloat(store.form.temperature);
      }
      if (store.form.seed) body.seed = parseInt(store.form.seed, 10);
      if (caps.includes('emotion')) {
        body.exaggeration = parseFloat(store.form.exaggeration);
        body.cfg_weight = parseFloat(store.form.cfg_weight);
      }

      const json = JSON.stringify(body, null, 2);
      return [
        'curl -X POST http://localhost:8000/v1/audio/speech \\',
        '  -H "Content-Type: application/json" \\',
        '  -H "X-Save-Output: true" \\',
        '  -H "x-auto-ssml: true" \\',
        "  -d '" + json.replace(/'/g, "'\\''") + "' \\",
        '  --output speech.mp3',
      ].join('\n');
    },
    curlReady() {
      return !this.curlText.startsWith('#');
    },
    curlStyle() {
      if (this.curlReady) {
        return { borderColor: 'rgba(63,185,80,0.3)', background: 'rgba(63,185,80,0.12)', color: 'var(--success)' };
      }
      return {};
    },
  },
  methods: {
    copyCurl() {
      if (!this.curlReady) return;
      navigator.clipboard.writeText(this.curlText).then(() => {
        this.$el.querySelector('.curl-copy-btn').textContent = 'Copied!';
        setTimeout(() => { const el = this.$el && this.$el.querySelector('.curl-copy-btn'); if (el) el.textContent = 'Copy'; }, 2000);
      }).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = this.curlText;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      });
    },
  },
};

// ── Add Voice Modal ──────────────────────────────────────────────────────────
comps['add-voice-modal'] = {
  template: '#add-voice-modal-template',
  data() {
    return {
      activeTab: 'upload',
      uploadFile: null,
      uploadName: '',
      uploadDescription: '',
      uploadStatus: '',
      uploadStatusClass: '',
      recordName: '',
      recordStatus: '',
      recordStatusClass: '',
      urlAddress: '',
      urlName: '',
      urlStatus: '',
      urlStatusClass: '',
      urlFetching: false,
      recording: false,
      _recorder: null,
      _chunks: [],
      _ctx: null,
      _analyser: null,
      _animFrame: null,
      _stream: null,
      stagedFile: null,
      stageTranscription: '',
      stageTranscribing: false,
      stageSaving: false,
      playing: false,
      currentTime: 0,
      duration: 0,
      seeker: false,
      _audio: null,
    };
  },
  computed: {
    hasAvailableStt() {
      return (this.$store.e2eModels || []).some(m => m.available);
    },
  },
  watch: {
    stagedFile(v) { if (!v && this._audio) this.stopPlayer(); },
  },
  methods: {
    switchTab(tab) { this.activeTab = tab; },
    async uploadSubmit() {
      const file = this.uploadFile;
      if (!file) {
        this.uploadStatus = 'Please select a file.';
        this.uploadStatusClass = 'error';
        return;
      }
      const btn = this.$el.querySelector('#upload-btn');
      if (btn) { btn.disabled = true; btn.textContent = 'Uploading...'; }
      try {
        const fd = new FormData();
        fd.append('file', file);
        if (this.uploadName.trim()) fd.append('name', this.uploadName.trim());
        if (this.uploadDescription.trim()) fd.append('description', this.uploadDescription.trim());
        const resp = await fetch('/voice/stage', { method: 'POST', body: fd });
        const data = await resp.json();
        if (!resp.ok) {
          this.uploadStatus = data.detail || 'Error ' + resp.status;
          this.uploadStatusClass = 'error';
          return;
        }
        this.stagedFile = data;
        this.uploadStatus = '';
        this.uploadFile = null;
        this.uploadName = '';
        this.uploadDescription = '';
      } catch (err) {
        this.uploadStatus = 'Network error: ' + err.message;
        this.uploadStatusClass = 'error';
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Upload'; }
      }
    },
    generateVoiceName() {
      const adj = ['Velvet','Crimson','Amber','Azure','Cosmic','Neon','Shadow','Crystal','Thunder','Silver','Golden','Midnight','Solar','Lunar','Ember','Frost','Storm','Echo','Phantom','Dusk','Dawn','Flux','Prism','Vortex','Nova','Sonic','Aurora','Iris','Haze','Drift','Pulse','Bloom','Ember','Cinder','Onyx','Jade','Copper','Woven','Quiet','Fading','Bright','Deep'];
      const noun = ['Voice','Echo','Wave','Tone','Chord','Rhythm','Melody','Harmony','Timbre','Resonance','Whisper','Song','Call','Hum','Drift','Pulse','Flow','Stream','Wind','Thunder','Rain','Storm','Light','Dream','Spirit','Bloom','Flux','Sway','Glide','Haze','Ember','Petal','Veil','Hymn','Reed','Chord'];
      return adj[Math.floor(Math.random() * adj.length)] + '_' + noun[Math.floor(Math.random() * noun.length)];
    },
    async startRecording() {
      if (!this.recordName.trim()) {
        this.recordName = this.generateVoiceName();
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        this.recordStatus = window.isSecureContext === false
          ? 'Recording requires HTTPS / localhost. Use http://localhost:8000.'
          : 'Recording not supported in this browser.';
        this.recordStatusClass = 'error';
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        this._stream = stream;
        this._chunks = [];
        this._recorder = new MediaRecorder(stream, {
          mimeType: MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm',
        });
        this._recorder.ondataavailable = (e => { if (e.data.size > 0) this._chunks.push(e.data); });
        this._recorder.onstop = () => this.onRecordingStop();
        this._recorder.start();
        this.recording = true;
        this.recordStatus = 'Recording... Speak now.';
        this.recordStatusClass = 'success';

        // Visualizer
        this._ctx = new AudioContext();
        const src = this._ctx.createMediaStreamSource(stream);
        this._analyser = this._ctx.createAnalyser();
        this._analyser.fftSize = 128;
        src.connect(this._analyser);
        this.drawWave();
      } catch (err) {
        this.recordStatus = 'Microphone access denied: ' + err.message;
        this.recordStatusClass = 'error';
      }
    },
    stopRecording() {
      if (this._recorder && this._recorder.state !== 'inactive') this._recorder.stop();
      this.recording = false;
    },
    async onRecordingStop() {
      if (this._stream) { this._stream.getTracks().forEach(t => t.stop()); this._stream = null; }
      if (this._animFrame) { cancelAnimationFrame(this._animFrame); this._animFrame = null; }
      this._analyser = null;
      if (this._ctx) { this._ctx.close(); this._ctx = null; }
      this.recording = false;
      if (!this._chunks.length) return;

      const blob = new Blob(this._chunks, { type: this._recorder ? this._recorder.mimeType : 'audio/webm' });
      const fd = new FormData();
      fd.append('file', blob, this.recordName.trim() + '.webm');
      fd.append('name', this.recordName.trim());
      this.recordStatus = 'Uploading...';
      this.recordStatusClass = '';
      try {
        const resp = await fetch('/voice/stage', { method: 'POST', body: fd });
        const data = await resp.json();
        if (!resp.ok) {
          this.recordStatus = data.detail || 'Error ' + resp.status;
          this.recordStatusClass = 'error';
          return;
        }
        this.stagedFile = data;
        this.recordStatus = '';
        this.recordName = '';
      } catch (err) {
        this.recordStatus = 'Network error: ' + err.message;
        this.recordStatusClass = 'error';
      }
    },
    async transcribeStage() {
      const e2eModels = this.$store.e2eModels || [];
      const sttModel = e2eModels.find(m => m.available && m.mlx_required) || e2eModels.find(m => m.available && m.id);
      if (!sttModel) {
        this.stageTranscription = 'No STT model available. Install a Whisper model first.';
        return;
      }
      this.stageTranscribing = true;
      this.stageTranscription = '';
      try {
        const resp = await fetch(this.stagedFile.url);
        const blob = await resp.blob();
        const fd = new FormData();
        fd.append('file', blob, this.stagedFile.name);
        fd.append('model', sttModel.id);
        fd.append('response_format', 'json');
        const sttResp = await fetch('/v1/audio/transcriptions', { method: 'POST', body: fd });
        const d = await sttResp.json();
        if (!sttResp.ok) {
          this.stageTranscription = d.detail || 'Transcription failed';
        } else {
          this.stageTranscription = d.text;
        }
      } catch (err) {
        this.stageTranscription = 'Error: ' + err.message;
      } finally {
        this.stageTranscribing = false;
      }
    },
    async saveStage() {
      this.stageSaving = true;
      try {
        const resp = await fetch('/voice/stage/' + encodeURIComponent(this.stagedFile.name) + '/save', { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) {
          this.stageSaving = false;
          return;
        }
        this.$store.voiceDetails.unshift(data);
        fetch('/v1/voices').then(r => r.json()).then(d => {
          if (d && d.data) applyVoiceData(this.$store, d.data);
        }).catch(() => {});
        const sel = this.$store.form.model;
        if (sel) {
          const m = this.$store.models.find(mdl => mdl.id === sel);
          if (m && m.voices && m.voices.cloneable && !m.voices.cloneable.includes(data.name)) {
            m.voices.cloneable.push(data.name);
          }
        }
        this.close();
      } catch (err) {
        this.stageSaving = false;
      }
    },
    async urlSubmit() {
      const url = this.urlAddress.trim();
      if (!url) {
        this.urlStatus = 'Please enter a URL.';
        this.urlStatusClass = 'error';
        return;
      }
      if (!/^https?:\/\//i.test(url)) {
        this.urlStatus = 'URL must start with http:// or https://';
        this.urlStatusClass = 'error';
        return;
      }
      this.urlFetching = true;
      this.urlStatus = '';
      try {
        const resp = await fetch('/voice/stage/url', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url, name: this.urlName.trim() || undefined }),
        });
        const data = await resp.json();
        if (!resp.ok) {
          this.urlStatus = data.detail || 'Error ' + resp.status;
          this.urlStatusClass = 'error';
          return;
        }
        this.stagedFile = data;
        this.urlAddress = '';
        this.urlName = '';
        this.urlStatus = '';
      } catch (err) {
        this.urlStatus = 'Network error: ' + err.message;
        this.urlStatusClass = 'error';
      } finally {
        this.urlFetching = false;
      }
    },
    async discardStage() {
      if (this.stagedFile) {
        try { await fetch('/voice/stage/' + encodeURIComponent(this.stagedFile.name), { method: 'DELETE' }); } catch {}
      }
      this.stagedFile = null;
      this.stageTranscription = '';
      this.urlAddress = '';
      this.urlName = '';
      this.urlStatus = '';
      this.activeTab = 'upload';
    },
    drawWave() {
      if (!this._analyser) return;
      const canvas = this.$el.querySelector('#recording-wave');
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      const bufferLength = this._analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);
      const w = canvas.width, h = canvas.height;

      const draw = () => {
        if (!this._analyser) return;
        this._animFrame = requestAnimationFrame(draw);
        this._analyser.getByteTimeDomainData(dataArray);
        ctx.fillStyle = '#0d1117';
        ctx.fillRect(0, 0, w, h);
        ctx.lineWidth = 2;
        ctx.strokeStyle = '#58a6ff';
        ctx.beginPath();
        const sliceWidth = w / bufferLength;
        let x = 0;
        for (let i = 0; i < bufferLength; i++) {
          const v = dataArray[i] / 128.0;
          const y = v * h / 2;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
          x += sliceWidth;
        }
        ctx.lineTo(w, h / 2);
        ctx.stroke();
      };
      draw();
    },
    formatTime(s) {
      if (!s || !isFinite(s)) return '0:00';
      const m = Math.floor(s / 60);
      const sec = Math.floor(s % 60);
      return m + ':' + (sec < 10 ? '0' : '') + sec;
    },
    togglePlayer() {
      if (this._audio && this.playing) {
        this.stopPlayer();
        return;
      }
      if (this.$store.currentAudio) {
        this.$store.currentAudio.pause();
        this.$store.currentAudio = null;
        this.$store.currentName = '';
      }
      const audio = new Audio(this.stagedFile.url);
      this._audio = audio;
      this.seeker = true;
      this.playing = true;
      this.$store.currentAudio = audio;
      this.$store.currentName = this.stagedFile.name;

      audio.addEventListener('timeupdate', () => {
        this.currentTime = audio.currentTime;
        this.duration = audio.duration || 0;
      });
      audio.addEventListener('ended', () => this.stopPlayer());
      audio.play().catch(() => this.stopPlayer());
    },
    stopPlayer() {
      if (this._audio) {
        this._audio.pause();
        this._audio = null;
      }
      this.playing = false;
      this.seeker = false;
      this.currentTime = 0;
      this.duration = 0;
      if (this.$store.currentName === this.stagedFile?.name) {
        this.$store.currentAudio = null;
        this.$store.currentName = '';
      }
    },
    seekPlayer(e) {
      const rect = e.currentTarget.getBoundingClientRect();
      const pct = (e.clientX - rect.left) / rect.width;
      const audio = this._audio || this.$store.currentAudio;
      if (audio && audio.duration) audio.currentTime = pct * audio.duration;
    },
    close() {
      this.stopPlayer();
      this.$store.showAddVoice = false;
    },
  },
};

// ── Params Modal ─────────────────────────────────────────────────────────────
comps['params-modal'] = {
  template: '#params-modal-template',
  computed: {
    out() { return this.$store.modalOut; },
  },
  methods: {
    fillForm() {
      const p = this.$store.regenParams;
      if (!p) return;
      if (p.model) {
        const opt = this.$store.models.find(m => m.id === p.model);
        if (opt) {
          this.$store.form.model = p.model;
        }
      }
      if (p.input) this.$store.form.text = p.input;
      if (p.speed != null) {
        this.$store.form.speed = Math.min(4, Math.max(0.25, parseFloat(p.speed)));
      }
      this.$store.form.seed = p.seed != null ? p.seed : null;
      if (p.voice) {
        const model = this.$store.models.find(m => m.id === (p.model || this.$store.form.model));
        const caps = model ? (model.capabilities || []) : [];
        if (caps.includes('voice_blend') && p.voice.includes(',')) {
          this.$store.blendMode = true;
          const obj = {};
          p.voice.split(',').forEach(part => {
            part = part.trim();
            const idx = part.lastIndexOf(':');
            if (idx > 0) {
              const v = part.slice(0, idx).trim();
              const w = parseFloat(part.slice(idx + 1)) || 0.5;
              obj[v] = w;
            } else {
              obj[part] = 0.5;
            }
          });
          this.$store.blendSelections = obj;
          this.$store.form.speaker_name = '';
        } else if (caps.includes('speaker') || caps.includes('voice_blend')) {
          this.$store.form.speaker_name = p.voice;
        } else if (caps.includes('voice_prompt')) {
          this.$store.form.voice_description = p.voice;
        } else if (caps.includes('voice_clone')) {
          this.$store.form.sample_voice_file = p.voice;
        }
      }
      if (p.exaggeration != null) this.$store.form.exaggeration = p.exaggeration;
      if (p.cfg_weight != null) this.$store.form.cfg_weight = p.cfg_weight;
      this.close();
    },
    deleteOut() {
      const out = this.out;
      if (!out) return;
      if (!confirm('Delete "' + out.name + '"?')) return;
      fetch('/output/' + encodeURIComponent(out.name), { method: 'DELETE' }).then(r => {
        if (!r.ok) return;
        if (this.$store.currentName === out.name) { if (this.$store.currentAudio) this.$store.currentAudio.pause(); this.$store.currentAudio = null; this.$store.currentName = ''; }
        this.$store.outputs = this.$store.outputs.filter(o => o.name !== out.name);
        this.close();
      });
    },
    close() { this.$store.showParams = false; },
    e2eResultClass(similarity) {
      if (similarity >= 0.9) return 'e2e-good';
      if (similarity >= 0.7) return 'e2e-ok';
      return 'e2e-bad';
    },
  },
};

// ── Manage Models Modal ──────────────────────────────────────────────────────
comps['manage-models-modal'] = {
  template: '#manage-models-modal-template',
  data() {
    return { activeTab: 'tts', expanded: {}, musicExpanded: {}, sttExpanded: {}, status: '', statusClass: '' };
  },
  computed: {
    groups() {
      const g = {};
      this.$store.models.forEach(m => {
        if (this._isMusic(m)) return;
        const e = m.engine || 'other';
        if (!g[e]) g[e] = [];
        g[e].push(m);
      });
      return g;
    },
    engineNames() {
      return Object.keys(this.groups).sort();
    },
    engineStats() {
      const s = {};
      this.engineNames.forEach(eng => {
        const models = this.groups[eng];
        const avail = models.filter(m => m.available).length;
        const gb = models.reduce((sum, m) => {
          if (!m.size) return sum;
          const p = m.size.match(/^([\d.]+)\s*(GB|MB)/);
          return p ? sum + (p[2] === 'GB' ? parseFloat(p[1]) : parseFloat(p[1]) / 1000) : sum;
        }, 0);
        s[eng] = { available: avail, total: models.length, totalGb: Math.round(gb * 10) / 10, availClass: avail === 0 ? 'avail-none' : avail < models.length ? 'avail-some' : 'avail-all' };
      });
      return s;
    },
    sttGroups() {
      const g = {};
      this.$store.e2eModels.forEach(m => {
        const e = m.engine || 'other';
        if (!g[e]) g[e] = [];
        g[e].push(m);
      });
      return g;
    },
    sttEngineNames() {
      return Object.keys(this.sttGroups).sort();
    },
    sttEngineStats() {
      const s = {};
      this.sttEngineNames.forEach(eng => {
        const models = this.sttGroups[eng];
        const avail = models.filter(m => m.available).length;
        const gb = models.reduce((sum, m) => {
          if (!m.size) return sum;
          const p = m.size.match(/^([\d.]+)\s*(GB|MB)/);
          return p ? sum + (p[2] === 'GB' ? parseFloat(p[1]) : parseFloat(p[1]) / 1000) : sum;
        }, 0);
        s[eng] = { available: avail, total: models.length, totalGb: Math.round(gb * 10) / 10, availClass: avail === 0 ? 'avail-none' : avail < models.length ? 'avail-some' : 'avail-all' };
      });
      return s;
    },
    musicGroups() {
      const g = {};
      this.$store.models.forEach(m => {
        if (!this._isMusic(m)) return;
        const e = m.engine || 'other';
        if (!g[e]) g[e] = [];
        g[e].push(m);
      });
      return g;
    },
    musicEngineNames() {
      return Object.keys(this.musicGroups).sort();
    },
    musicEngineStats() {
      const s = {};
      this.musicEngineNames.forEach(eng => {
        const models = this.musicGroups[eng];
        const avail = models.filter(m => m.available).length;
        const gb = models.reduce((sum, m) => {
          if (!m.size) return sum;
          const p = m.size.match(/^([\d.]+)\s*(GB|MB)/);
          return p ? sum + (p[2] === 'GB' ? parseFloat(p[1]) : parseFloat(p[1]) / 1000) : sum;
        }, 0);
        s[eng] = { available: avail, total: models.length, totalGb: Math.round(gb * 10) / 10, availClass: avail === 0 ? 'avail-none' : avail < models.length ? 'avail-some' : 'avail-all' };
      });
      return s;
    },
  },
  mounted() {},
  methods: {
    switchTab(tab) { this.activeTab = tab; },
    toggleEngine(name) {
      this.expanded[name] = !this.expanded[name];
    },
    _isMusic(m) {
      return m.capabilities && (m.capabilities.includes('text_to_music') || m.capabilities.includes('text_to_sfx'));
    },
    toggleMusicEngine(name) {
      this.musicExpanded[name] = !this.musicExpanded[name];
    },
    toggleSttEngine(name) {
      this.sttExpanded[name] = !this.sttExpanded[name];
    },
    derivedRemove(item) {
      if (!item.install || !item.install.commands) return null;
      const removes = item.install.commands.map(cmd => this._toRemove(cmd)).filter(Boolean);
      return removes.length ? removes : null;
    },
    _toRemove(cmd) {
      const hf = cmd.match(/hf\s+download\s+\S+\s+--local-dir\s+(\S+)/);
      if (hf) return 'rm -rf ' + hf[1];
      const curl = cmd.match(/curl\s+-LO\s+(\S+)\s+--output-dir\s+(\S+)/);
      if (curl) {
        const dir = curl[2], file = curl[1].split('/').pop();
        return file ? 'rm ' + dir + '/' + file : null;
      }
      const pip = cmd.match(/python\s+-m\s+piper\.download_voices\s+--download-dir\s+(\S+)\s+(\S+)/);
      if (pip) return 'rm ' + pip[1] + '/' + pip[2] + '.*';
      return null;
    },
    confirmDownload(item) {
      const cmds = item.install.commands.join('\n');
      if (!confirm('Download "' + item.name + '" (' + item.id + ')?\n\nIt is recommended to run these commands in your terminal:\n\n' + cmds + '\n\nCopy commands to clipboard?')) return;
      this._copyAll(item.install.commands);
      this._flash('Download commands copied to clipboard!', 'success');
    },
    confirmRemove(item) {
      const rm = this.derivedRemove(item);
      if (!rm) {
        if (!confirm('Remove "' + item.name + '" (' + item.id + ')?\n\nNo automatic remove command available. Delete the model directory manually from models/')) return;
        return;
      }
      const text = rm.join('\n');
      if (!confirm('Remove "' + item.name + '" (' + item.id + ')?\n\nRun these commands in your terminal (recommended):\n\n' + text + '\n\nCopy commands to clipboard?')) return;
      this._copyAll(rm);
      this._flash('Remove commands copied to clipboard!', 'success');
    },
    copyAll(item) {
      const all = [];
      if (item.install && item.install.commands) all.push(...item.install.commands);
      const rm = this.derivedRemove(item);
      if (rm) all.push(...rm);
      if (!all.length) return;
      this._copyAll(all);
      this._flash('All commands copied to clipboard!', 'success');
    },
    _copyAll(cmds) {
      const text = cmds.join('\n');
      navigator.clipboard.writeText(text).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      });
    },
    copyCmd(cmd) {
      navigator.clipboard.writeText(cmd).then(() => {}).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = cmd;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      });
    },
    _flash(msg, cls) {
      this.status = msg;
      this.statusClass = cls;
      clearTimeout(this._flashTimer);
      this._flashTimer = setTimeout(() => { this.status = ''; }, 2500);
    },
    close() { this.$store.showManage = false; },
  },
};

// ── Batch Detail Modal ────────────────────────────────────────────────────
comps['batch-detail-modal'] = {
  template: '#batch-detail-modal-template',
  computed: {
    items() { return this.$store.batchDetailItems; },
    batchType() {
      if (!this.items.length) return 'unknown';
      const models = new Set();
      const voices = new Set();
      this.items.forEach(i => {
        if (i.params) {
          models.add(i.params.model);
          if (i.params.voice) voices.add(i.params.voice);
        }
      });
      if (voices.size === 1) {
        const v = [...voices][0];
        return v.endsWith('.wav') ? 'clone' : 'prompt';
      }
      return 'multivoice';
    },
    modalTitle() {
      if (!this.items.length) return 'Batch';
      const map = { multivoice: 'Speaker', clone: 'Voice Clone', prompt: 'Voice Prompt' };
      return 'Batch - ' + (map[this.batchType] || '');
    },
    sharedText() {
      return (this.items[0] && this.items[0].params && this.items[0].params.input) || '';
    },
    singularInfo() {
      if (!this.items.length) return null;
      if (this.batchType === 'multivoice') {
        const mId = this.items[0].params && this.items[0].params.model;
        if (!mId) return null;
        const m = this.$store.models.find(x => x.id === mId);
        return { label: 'Model', value: m ? m.name : mId };
      }
      const v = this.items[0].params && this.items[0].params.voice;
      if (!v) return null;
      const label = this.batchType === 'clone' ? 'Voice' : 'Voice Prompt';
      return { label, value: this.batchType === 'clone' ? v : '"' + v + '"' };
    },
    totalGenerated() {
      return this.items.length + ' generated';
    },
  },
  methods: {
    itemDiff(item) {
      const p = item.params || {};
      if (this.batchType === 'multivoice') return p.voice || '';
      const m = this.$store.models.find(x => x.id === p.model);
      return m ? m.name : (p.model || '');
    },
    e2eResultClass(similarity) {
      if (similarity >= 0.9) return 'e2e-good';
      if (similarity >= 0.7) return 'e2e-ok';
      return 'e2e-bad';
    },
    close() {
      this.$store.showBatchDetail = false;
      this.$store.batchDetailItems = [];
      this.$store.batchDetailLabel = '';
    },
    deleteItem(name) {
      if (!confirm('Delete "' + name + '"?')) return;
      fetch('/output/' + encodeURIComponent(name), { method: 'DELETE' }).then(r => {
        if (!r.ok) return;
        if (this.$store.currentName === name) { this.$store.currentAudio.pause(); this.$store.currentAudio = null; this.$store.currentName = ''; }
        this.$store.batchDetailItems = this.$store.batchDetailItems.filter(o => o.name !== name);
        this.$store.outputs = this.$store.outputs.filter(o => o.name !== name);
      });
    },
  },
};

})();
