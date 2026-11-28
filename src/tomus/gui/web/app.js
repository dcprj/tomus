/**
 * Tomus Web UI — Script de Controle e Comunicação com o Motor Python
 */

(function () {
  'use strict';

  // --- Estado da Aplicação ---
  const state = {
    sourceDir: '',
    targetDir: '',
    fileOperation: 'copy', // 'copy' | 'move'
    provider: 'gemini',
    recursive: true,
    dryRun: false,
    isRunning: false,
    items: [], // [{ source_path, destination_path, status, stage, message, title, authors, year, grande_area, area_basica, tipo, confidence, used_ocr, sha256, reasoning, error_message }]
    selectedPath: null,
    activeFilter: 'all',
    searchQuery: '',
    activeAreaFilter: null,
    batchStartTime: null,
  };

  // --- Elementos do DOM ---
  const el = {
    sourcePath: document.getElementById('sourcePathDisplay'),
    targetPath: document.getElementById('targetPathDisplay'),
    btnBrowseSource: document.getElementById('btnBrowseSource'),
    btnBrowseTarget: document.getElementById('btnBrowseTarget'),
    btnOrganize: document.getElementById('btnOrganize'),
    organizeLabel: document.getElementById('organizeLabel'),
    organizeIcon: document.getElementById('organizeIcon'),
    modelSelect: document.getElementById('modelSelect'),
    keyBadge: document.getElementById('keyBadge'),
    keyBadgeText: document.getElementById('keyBadgeText'),
    btnModeCopy: document.getElementById('btnModeCopy'),
    btnModeMove: document.getElementById('btnModeMove'),
    chkRecursive: document.getElementById('chkRecursive'),
    chkDryRun: document.getElementById('chkDryRun'),
    btnPreferences: document.getElementById('btnPreferences'),
    btnCache: document.getElementById('btnCache'),
    
    // Sidebar
    filterList: document.getElementById('statusFilterList'),
    cntTotal: document.getElementById('cntTotal'),
    cntOrganized: document.getElementById('cntOrganized'),
    cntManual: document.getElementById('cntManual'),
    cntDuplicate: document.getElementById('cntDuplicate'),
    cntIgnored: document.getElementById('cntIgnored'),
    cntError: document.getElementById('cntError'),
    cntObsolete: document.getElementById('cntObsolete'),
    capesTree: document.getElementById('capesTree'),

    // Table
    searchInput: document.getElementById('searchInput'),
    btnClearSearch: document.getElementById('btnClearSearch'),
    docTableBody: document.getElementById('docTableBody'),
    tableEmptyState: document.getElementById('tableEmptyState'),
    tablePanel: document.querySelector('.table-panel'),

    // Inspector
    inspectorEmpty: document.getElementById('inspectorEmpty'),
    inspectorPanel: document.getElementById('inspectorPanel'),
    inspectorContent: document.getElementById('inspectorContent'),
    inspStatusBadge: document.getElementById('inspStatusBadge'),
    inspStatusIcon: document.getElementById('inspStatusIcon'),
    inspStatusText: document.getElementById('inspStatusText'),
    inspAbntCard: document.getElementById('inspAbntCard'),
    inspAbntCitation: document.getElementById('inspAbntCitation'),
    btnCopyCitation: document.getElementById('btnCopyCitation'),
    inspTriageCard: document.getElementById('inspTriageCard'),
    inspTriageReason: document.getElementById('inspTriageReason'),
    triageGrandeArea: document.getElementById('triageGrandeArea'),
    triageAreaBasica: document.getElementById('triageAreaBasica'),
    triageSubarea: document.getElementById('triageSubarea'),
    triageTitle: document.getElementById('triageTitle'),
    triageSubtitle: document.getElementById('triageSubtitle'),
    triageAuthors: document.getElementById('triageAuthors'),
    triageYear: document.getElementById('triageYear'),
    triageTipo: document.getElementById('triageTipo'),
    btnApproveTriage: document.getElementById('btnApproveTriage'),
    kvGrandeArea: document.getElementById('kvGrandeArea'),
    kvAreaBasica: document.getElementById('kvAreaBasica'),
    kvSubarea: document.getElementById('kvSubarea'),
    kvEspecialidade: document.getElementById('kvEspecialidade'),
    kvTipo: document.getElementById('kvTipo'),
    kvConfianca: document.getElementById('kvConfianca'),
    kvOrigem: document.getElementById('kvOrigem'),
    kvDestino: document.getElementById('kvDestino'),
    kvSha256: document.getElementById('kvSha256'),
    btnOpenPdf: document.getElementById('btnOpenPdf'),
    btnRevealFolder: document.getElementById('btnRevealFolder'),

    // Status bar
    progressBarFill: document.getElementById('progressBarFill'),
    progressPct: document.getElementById('progressPct'),
    stageIndicator: document.getElementById('stageIndicator'),
    countIndicator: document.getElementById('countIndicator'),
    remainingIndicator: document.getElementById('remainingIndicator'),
    avgTimeIndicator: document.getElementById('avgTimeIndicator'),
    etaIndicator: document.getElementById('etaIndicator'),
    qualityMetric: document.getElementById('qualityMetric'),

    // Completion banner
    completionBanner: document.getElementById('completionBanner'),
    bannerHeadline: document.getElementById('bannerHeadline'),
    bannerDetails: document.getElementById('bannerDetails'),
    btnClearBatch: document.getElementById('btnClearBatch'),

    // Completion modal popup
    completionModal: document.getElementById('completionModal'),
    modalTitle: document.getElementById('modalTitle'),
    modalSubtitle: document.getElementById('modalSubtitle'),
    modalIconWrap: document.getElementById('modalIconWrap'),
    modalIconSvg: document.getElementById('modalIconSvg'),
    modalCountOrganized: document.getElementById('modalCountOrganized'),
    modalCountReview: document.getElementById('modalCountReview'),
    modalCountDuplicate: document.getElementById('modalCountDuplicate'),
    modalCountError: document.getElementById('modalCountError'),
    modalCountObsolete: document.getElementById('modalCountObsolete'),
    modalQualityBadge: document.getElementById('modalQualityBadge'),
    modalQualityText: document.getElementById('modalQualityText'),
    btnModalClose: document.getElementById('btnModalClose'),
    btnModalReview: document.getElementById('btnModalReview'),
    btnModalClear: document.getElementById('btnModalClear'),

    // About modal dialog
    btnAbout: document.getElementById('btnAbout'),
    aboutModal: document.getElementById('aboutModal'),
    btnAboutClose: document.getElementById('btnAboutClose'),
    btnAboutOk: document.getElementById('btnAboutOk'),
    btnCopyPix: document.getElementById('btnCopyPix'),
    pixKeyInput: document.getElementById('pixKeyInput'),
  };

  // --- Dicionário Taxonômico CAPES/CNPq (carregado dinamicamente do backend via getInitialState) ---
  let CAPES_TAXONOMY = {};  // preenchido pelo backend via getInitialState()
  let AREA_TO_GRANDE_AREA = {};  // preenchido pelo backend via getInitialState()

  // --- Inicialização do QWebChannel ---
  let backend = null;

  function initWebChannel() {
    if (typeof QWebChannel === 'undefined' || typeof qt === 'undefined' || !qt.webChannelTransport) {
      console.warn('QWebChannel ou qt não disponível — rodando em modo visual simulado.');
      setupMockData();
      return;
    }

    new QWebChannel(qt.webChannelTransport, function (channel) {
      backend = channel.objects.backend;
      window.backend = backend;
      console.log('QWebChannel conectado com sucesso ao backend Python!');

      // Sinais vindos do Python
      backend.pipelineEvent.connect(handlePipelineEvent);
      backend.pipelineFinished.connect(handlePipelineFinished);
      backend.sourceChanged.connect(function (path) { setSource(path); });
      backend.targetChanged.connect(function (path) { setTarget(path); });
      backend.keyStatusChanged.connect(function (hasKey) {
        if (backend && backend.checkProviderKey && state.provider) {
          backend.checkProviderKey(state.provider).then(updateKeyBadge);
        } else {
          updateKeyBadge(hasKey);
        }
      });

      // Obter estado inicial
      backend.getInitialState().then(function (initStateJson) {
        if (!initStateJson) return;
        const init = JSON.parse(initStateJson);
        if (init.source) setSource(init.source);
        if (init.target) setTarget(init.target);
        if (init.provider) {
          el.modelSelect.value = init.provider;
          state.provider = init.provider;
        }
        if (backend.checkProviderKey) {
          backend.checkProviderKey(state.provider).then(updateKeyBadge);
        } else if (init.hasKey !== undefined) {
          updateKeyBadge(init.hasKey);
        }
        // Carregar taxonomia oficial do servidor
        if (init.taxonomy) {
          const areas = init.taxonomy.areas || {};
          // Limpar objetos sem criar chave 'length' (objeto != array)
          Object.keys(CAPES_TAXONOMY).forEach(k => delete CAPES_TAXONOMY[k]);
          Object.assign(CAPES_TAXONOMY, areas);
          Object.keys(AREA_TO_GRANDE_AREA).forEach(k => delete AREA_TO_GRANDE_AREA[k]);
          Object.assign(AREA_TO_GRANDE_AREA, {});
          for (const [ga, basicas] of Object.entries(areas)) {
            for (const b of basicas) {
              AREA_TO_GRANDE_AREA[b] = ga;
            }
          }
          if (el.triageAreaBasica) {
            el.triageAreaBasica.innerHTML = buildTriageAreaOptionsHtml('');
          }
        }
      });
    });
  }

  // --- Handlers de Eventos do Pipeline (Tempo Real) ---
  function handlePipelineEvent(eventJson) {
    try {
      const ev = typeof eventJson === 'string' ? JSON.parse(eventJson) : eventJson;
      if (!ev) return;

      // Atualizar barra de progresso e métricas do rodapé
      if (ev.total_files && ev.completed_files !== undefined) {
        const pct = Math.round((ev.completed_files / ev.total_files) * 100);
        el.progressBarFill.style.width = pct + '%';
        el.progressPct.textContent = pct + '%';
        el.countIndicator.textContent = ev.completed_files + ' / ' + ev.total_files + ' processados';
        const remaining = ev.total_files - ev.completed_files;
        el.remainingIndicator.textContent = 'Restam: ' + remaining;

        // Cálculo dinâmico das métricas (média por arquivo e total estimado)
        if (state.batchStartTime && ev.completed_files > 0) {
          const elapsedSec = Math.max(1, (Date.now() - state.batchStartTime) / 1000);
          const avgSec = elapsedSec / ev.completed_files;

          // Formatar média por arquivo
          let avgStr = '';
          if (avgSec >= 60) {
            avgStr = Math.round(avgSec / 60) + ' min';
          } else {
            avgStr = (avgSec < 10 ? avgSec.toFixed(1) : Math.round(avgSec)) + ' s';
          }
          if (el.avgTimeIndicator) el.avgTimeIndicator.textContent = 'média por arquivo: ' + avgStr;

          // Formatar total estimado restante
          if (remaining > 0) {
            const remSec = Math.round(avgSec * remaining);
            let etaStr = '';
            if (remSec >= 3600) {
              const h = Math.floor(remSec / 3600);
              const m = Math.round((remSec % 3600) / 60);
              etaStr = h + ' h e ' + m + ' min';
            } else if (remSec >= 60) {
              etaStr = Math.round(remSec / 60) + ' min';
            } else {
              etaStr = remSec + ' s';
            }
            if (el.etaIndicator) el.etaIndicator.textContent = 'Total estimado: ' + etaStr;
          } else {
            if (el.etaIndicator) el.etaIndicator.textContent = 'Total estimado: Concluindo...';
          }
        }
      }
      if (ev.stage) {
        el.stageIndicator.textContent = 'Estágio: ' + formatStageName(ev.stage);
      }

      // Filtrar eventos de diretório / ciclo de vida
      if (ev.stage === 'scanner' && (ev.status === 'completed' || (ev.message && (ev.message.startsWith('Varredura') || ev.message.includes('PDF(s)'))))) {
        return;
      }
      if (ev.stage === 'pipeline' && ev.status === 'completed') {
        return;
      }
      if (!ev.source_path) return;

      upsertItemFromEvent(ev);
    } catch (err) {
      console.error('[Tomus] Erro ao processar evento:', err, eventJson);
    }
  }

  function handlePipelineFinished(summaryJson) {
    try {
      state.isRunning = false;
      updateOrganizeButton();

      if (!summaryJson) return;
      const summary = typeof summaryJson === 'string' ? JSON.parse(summaryJson) : summaryJson;

      if (summary.error) {
        alert('Erro no processamento do acervo:\n\n' + summary.error);
        return;
      }

      el.progressBarFill.style.width = '100%';
      el.progressPct.textContent = '100%';
      el.stageIndicator.textContent = 'Estágio: Concluído';

      // Rodapé correto ao concluir: X / X processados e Restam: 0
      const total = summary.total_scanned || 0;
      el.countIndicator.textContent = total + ' / ' + total + ' processados';
      el.remainingIndicator.textContent = 'Restam: 0';

      if (state.batchStartTime) {
        const totalElapsedSec = Math.max(1, (Date.now() - state.batchStartTime) / 1000);
        let totStr = '';
        if (totalElapsedSec >= 3600) {
          totStr = Math.floor(totalElapsedSec / 3600) + ' h e ' + Math.round((totalElapsedSec % 3600) / 60) + ' min';
        } else if (totalElapsedSec >= 60) {
          totStr = Math.round(totalElapsedSec / 60) + ' min';
        } else {
          totStr = Math.round(totalElapsedSec) + ' s';
        }
        if (el.etaIndicator) el.etaIndicator.textContent = 'Tempo total: ' + totStr;
      }

      // Métrica de qualidade
      if (summary.manual_review_ratio !== undefined) {
        const ratioPct = (summary.manual_review_ratio * 100).toFixed(1);
        const isOverCeiling = summary.exceeded_manual_review_ceiling;
        el.qualityMetric.className = 'quality-metric ' + (isOverCeiling ? 'badge-red' : 'badge-green');
        el.qualityMetric.textContent = 'Revisão Manual: ' + ratioPct + '% (' + (isOverCeiling ? 'acima' : 'dentro') + ' do teto <= 20%)';
      }

      // Exibir banner informativo de conclusão
      if (el.completionBanner) {
        const org = summary.organized_count || 0;
        const rev = summary.manual_review_count || 0;
        const dup = summary.duplicate_skipped_count || 0;
        const err = summary.error_count || 0;
        const obs = summary.obsolete_count || 0;
        el.bannerHeadline.textContent = summary.was_cancelled
          ? 'Processamento interrompido pelo usuário.'
          : 'Organização do lote concluída com sucesso!';
        el.bannerDetails.textContent = `${org} organizado(s) • ${rev} revisão manual • ${dup} duplicata(s) • ${obs} obsoleto(s) • ${err} erro(s). Clique aqui para limpar e iniciar novo lote.`;
        el.completionBanner.style.display = 'block';
      }

      // Abrir Modal Popup em destaque
      openCompletionModal(summary);

      // Selecionar o primeiro item automaticamente se nada estiver selecionado
      if (state.items.length > 0 && !state.selectedPath) {
        selectItem(state.items[0].source_path);
      }
    } catch (err) {
      console.error('[Tomus] Erro ao finalizar pipeline:', err, summaryJson);
    }
  }

  // --- Som Suave de Conclusão de Lote (Web Audio API nativo) ---
  function playCompletionSound() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const now = ctx.currentTime;

      // Primeiro tom suave (acorde elegante: C5 523Hz -> E5 659Hz)
      const osc1 = ctx.createOscillator();
      const gain1 = ctx.createGain();
      osc1.type = 'sine';
      osc1.frequency.setValueAtTime(523.25, now);
      gain1.gain.setValueAtTime(0.08, now);
      gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
      osc1.connect(gain1);
      gain1.connect(ctx.destination);
      osc1.start(now);
      osc1.stop(now + 0.35);

      // Segundo tom harmônico
      const osc2 = ctx.createOscillator();
      const gain2 = ctx.createGain();
      osc2.type = 'sine';
      osc2.frequency.setValueAtTime(659.25, now + 0.12);
      gain2.gain.setValueAtTime(0.08, now + 0.12);
      gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.55);
      osc2.connect(gain2);
      gain2.connect(ctx.destination);
      osc2.start(now + 0.12);
      osc2.stop(now + 0.55);
    } catch (_) {
      // Falha silenciosa se áudio estiver desabilitado no ambiente
    }
  }

  // --- Modal Popup de Conclusão ---
  function openCompletionModal(summary) {
    if (!el.completionModal) return;
    playCompletionSound();

    const org = summary.organized_count || 0;
    const rev = summary.manual_review_count || 0;
    const dup = summary.duplicate_skipped_count || 0;
    const err = summary.error_count || 0;
    const obs = summary.obsolete_count || 0;

    if (el.modalCountOrganized) el.modalCountOrganized.textContent = String(org);
    if (el.modalCountReview) el.modalCountReview.textContent = String(rev);
    if (el.modalCountDuplicate) el.modalCountDuplicate.textContent = String(dup);
    if (el.modalCountError) el.modalCountError.textContent = String(err);
    if (el.modalCountObsolete) el.modalCountObsolete.textContent = String(obs);

    if (summary.was_cancelled) {
      if (el.modalIconWrap) el.modalIconWrap.className = 'modal-icon-wrap icon-warn';
      if (el.modalIconSvg) {
        el.modalIconSvg.innerHTML = '<polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"></polygon><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line>';
      }
      if (el.modalTitle) el.modalTitle.textContent = 'Processamento Interrompido';
      if (el.modalSubtitle) el.modalSubtitle.textContent = 'A organização do acervo foi interrompida pelo usuário antes da conclusão total.';
    } else if (err > 0 && org === 0) {
      if (el.modalIconWrap) el.modalIconWrap.className = 'modal-icon-wrap icon-error';
      if (el.modalIconSvg) {
        el.modalIconSvg.innerHTML = '<circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line>';
      }
      if (el.modalTitle) el.modalTitle.textContent = 'Atenção: Erros no Processamento';
      if (el.modalSubtitle) el.modalSubtitle.textContent = 'Ocorreram falhas durante o processamento do lote. Verifique as mensagens de erro na tabela.';
    } else {
      if (el.modalIconWrap) el.modalIconWrap.className = 'modal-icon-wrap icon-success';
      if (el.modalIconSvg) {
        el.modalIconSvg.innerHTML = '<polyline points="20 6 9 17 4 12"></polyline>';
      }
      if (el.modalTitle) el.modalTitle.textContent = 'Organização Concluída com Sucesso!';
      if (el.modalSubtitle) el.modalSubtitle.textContent = 'O lote de documentos foi processado e catalogado conforme as diretrizes CAPES/CNPq.';
    }

    if (summary.manual_review_ratio !== undefined) {
      const ratioPct = (summary.manual_review_ratio * 100).toFixed(1);
      const isOverCeiling = summary.exceeded_manual_review_ceiling;
      if (el.modalQualityBadge) {
        el.modalQualityBadge.className = 'modal-quality-badge ' + (isOverCeiling ? 'badge-red' : 'badge-green');
        el.modalQualityBadge.style.display = 'inline-flex';
      }
      if (el.modalQualityText) {
        el.modalQualityText.textContent = `Taxa de Revisão Manual: ${ratioPct}% (${isOverCeiling ? 'acima' : 'dentro'} do teto ≤ 20%)`;
      }
    } else if (el.modalQualityBadge) {
      el.modalQualityBadge.style.display = 'none';
    }

    el.completionModal.style.display = 'flex';
  }

  function closeCompletionModal() {
    if (el.completionModal) {
      el.completionModal.style.display = 'none';
    }
  }

  window.handlePipelineEvent = handlePipelineEvent;
  window.handlePipelineFinished = handlePipelineFinished;

  function formatStageName(stage) {
    const map = {
      scanner: 'Scanner',
      cache: 'Cache',
      extractor: 'Extração de Texto',
      enricher: 'Enriquecimento',
      llm: 'Classificação LLM',
      organizer: 'Materialização',
      pipeline: 'Concluído'
    };
    return map[stage] || stage;
  }

  // --- Upsert de Item na Grade ---
  function upsertItemFromEvent(ev) {
    if (!ev || !ev.source_path) return;
    if (ev.source_path === state.sourceDir || ev.source_path === state.targetDir) return;

    let item = state.items.find(i => i.source_path === ev.source_path);
    const isNew = !item;

    if (isNew) {
      item = {
        source_path: ev.source_path,
        destination_path: '',
        sha256: '',
        status: 'processing',
        stage: ev.stage,
        message: ev.message,
        title: '',
        subtitle: '',
        authors: [],
        year: null,
        grande_area: '',
        area_basica: '',
        subarea: '',
        especialidade: '',
        tipo: '',
        confidence: 0,
        used_ocr: false,
        reasoning: '',
        error_message: '',
      };
      state.items.push(item);
    }

    item.stage = ev.stage;
    item.message = ev.message;

    // Atualizar classificação parcial ou completa
    if (ev.classification) {
      const cls = ev.classification;
      item.title = cls.title || item.title;
      item.subtitle = cls.subtitle || item.subtitle;
      item.authors = cls.authors || item.authors;
      item.year = cls.year !== undefined ? cls.year : item.year;
      item.grande_area = cls.grande_area || item.grande_area;
      item.area_basica = cls.area_basica || item.area_basica;
      item.subarea = cls.subarea || item.subarea || '';
      item.especialidade = cls.especialidade || item.especialidade || '';
      item.tipo = cls.tipo || item.tipo;
      item.confidence = cls.confidence_score !== undefined ? cls.confidence_score : item.confidence;
      item.used_ocr = cls.used_ocr !== undefined ? cls.used_ocr : item.used_ocr;
      item.reasoning = cls.reasoning || item.reasoning;
      item.publisher = cls.publisher || item.publisher || '';
      item.city = cls.city || item.city || '';
      item.edition = cls.edition || item.edition || '';
      item.journal_name = cls.journal_name || item.journal_name || '';
      item.volume = cls.volume || item.volume || '';
      item.number = cls.number || item.number || '';
      item.pages = cls.pages || item.pages || '';
      item.doi = cls.doi || item.doi || '';
      item.isbn = cls.isbn || item.isbn || '';
    }

    if (ev.destination_path) {
      item.destination_path = ev.destination_path;
    }
    if (ev.sha256) {
      item.sha256 = ev.sha256;
    }

    // Status final
    const terminalStatuses = ['organized', 'manual_review', 'duplicate_skipped', 'ignored_non_pdf', 'error', 'obsolete'];
    if (terminalStatuses.includes(ev.status)) {
      item.status = ev.status;
    } else if (ev.status === 'ignored') {
      item.status = 'ignored_non_pdf';
    }

    updateCounters();
    updateTaxonomyTree();
    renderTable();

    // Se o item selecionado foi atualizado, re-renderizar inspetor
    if (state.selectedPath === item.source_path) {
      renderInspector(item);
    }
  }

  // --- Atualização de Contadores ---
  function updateCounters() {
    const counts = {
      total: state.items.length,
      organized: state.items.filter(i => i.status === 'organized').length,
      manual_review: state.items.filter(i => i.status === 'manual_review').length,
      duplicate_skipped: state.items.filter(i => i.status === 'duplicate_skipped').length,
      ignored_non_pdf: state.items.filter(i => i.status === 'ignored_non_pdf').length,
      error: state.items.filter(i => i.status === 'error').length,
      obsolete: state.items.filter(i => i.status === 'obsolete').length,
    };

    el.cntTotal.textContent = counts.total;
    el.cntOrganized.textContent = counts.organized;
    el.cntManual.textContent = counts.manual_review;
    el.cntDuplicate.textContent = counts.duplicate_skipped;
    el.cntIgnored.textContent = counts.ignored_non_pdf;
    el.cntError.textContent = counts.error;
    if (el.cntObsolete) el.cntObsolete.textContent = counts.obsolete;
  }

  // --- Atualização da Árvore CAPES/CNPq ---
  function updateTaxonomyTree() {
    const tree = {};
    for (const it of state.items) {
      const area = it.area_basica || it.grande_area;
      if (!area) continue;
      const sub = it.subarea || 'Geral';
      if (!tree[area]) tree[area] = {};
      if (!tree[area][sub]) tree[area][sub] = 0;
      tree[area][sub]++;
    }

    const areas = Object.keys(tree).sort();
    if (areas.length === 0) {
      el.capesTree.innerHTML = '<div class="tree-empty">Nenhuma área classificada ainda</div>';
      return;
    }

    let html = '';
    for (const ab of areas) {
      const abTotal = Object.values(tree[ab]).reduce((a, b) => a + b, 0);
      const isAbSelected = state.activeAreaFilter === ab;
      html += `<div class="tree-node">
        <div class="tree-header ${isAbSelected ? 'selected' : ''}" data-area="${escapeHtml(ab)}" data-level="area_basica">
          <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
          <strong>${escapeHtml(ab)}</strong>
          <span class="count-pill badge-gray">${abTotal}</span>
        </div>
        <div class="tree-children">`;

      const subs = tree[ab];
      for (const sub of Object.keys(subs).sort()) {
        const isSubSelected = state.activeAreaFilter === sub;
        html += `<div class="tree-subnode">
          <div class="tree-header ${isSubSelected ? 'selected' : ''}" data-area="${escapeHtml(sub)}" data-level="subarea">
            <span style="color: var(--text-muted);">&bull;</span>
            <span>${escapeHtml(sub)}</span>
            <span class="count-pill badge-gray">${subs[sub]}</span>
          </div>
        </div>`;
      }
      html += `</div></div>`;
    }
    el.capesTree.innerHTML = html;

    // Eventos de clique na árvore
    el.capesTree.querySelectorAll('.tree-header').forEach(hdr => {
      hdr.addEventListener('click', () => {
        const area = hdr.getAttribute('data-area');
        if (state.activeAreaFilter === area) {
          state.activeAreaFilter = null; // Toggle off
        } else {
          state.activeAreaFilter = area;
        }
        updateTaxonomyTree();
        renderTable();
      });
    });
  }

  // --- Renderização da Tabela de Documentos ---
  function renderTable() {
    const query = state.searchQuery.trim().toLowerCase();
    const filter = state.activeFilter;
    const areaFilter = state.activeAreaFilter;

    const filtered = state.items.filter(item => {
      // Filtro de status da sidebar
      if (filter !== 'all' && item.status !== filter) return false;

      // Filtro da árvore CAPES
      if (areaFilter && item.grande_area !== areaFilter && item.area_basica !== areaFilter && item.subarea !== areaFilter) return false;

      // Filtro de busca textual
      if (query) {
        const titleMatch = (item.title || getFilename(item.source_path)).toLowerCase().includes(query);
        const authorsMatch = (item.authors || []).join(' ').toLowerCase().includes(query);
        const yearMatch = (item.year ? String(item.year) : '').includes(query);
        const areaMatch = (item.grande_area + ' ' + item.area_basica).toLowerCase().includes(query);
        const typeMatch = (item.tipo || '').toLowerCase().includes(query);
        const fileMatch = item.source_path.toLowerCase().includes(query);
        if (!titleMatch && !authorsMatch && !yearMatch && !areaMatch && !typeMatch && !fileMatch) {
          return false;
        }
      }

      return true;
    });

    if (filtered.length === 0) {
      el.docTableBody.innerHTML = '';
      el.tableEmptyState.style.display = 'flex';
      el.tableEmptyState.innerHTML = state.items.length === 0
        ? '<p>Nenhum documento no lote. Selecione a pasta de origem e clique em <strong>Organizar Acervo</strong>.</p>'
        : '<p>Nenhum documento encontrado para o filtro ativo.</p>';
      return;
    }

    el.tableEmptyState.style.display = 'none';

    let html = '';
    for (const it of filtered) {
      const isSelected = state.selectedPath === it.source_path;
      const displayTitle = it.title || getFilename(it.source_path);
      const authorsStr = (it.authors && it.authors.length > 0) ? it.authors.join('; ') : '—';
      const yearStr = it.year ? String(it.year) : 's.d.';
      const areaStr = it.area_basica ? (it.area_basica + (it.subarea ? ' › ' + it.subarea : '')) : (it.grande_area || '—');
      const typeStr = it.tipo || '—';
      const confStr = it.confidence ? it.confidence.toFixed(2) : '—';

      html += `<tr class="${isSelected ? 'selected' : ''}" data-path="${escapeHtml(it.source_path)}">
        <td class="col-status">${renderStatusPill(it.status)}</td>
        <td class="col-title" title="${escapeHtml(displayTitle)}"><strong>${escapeHtml(displayTitle)}</strong></td>
        <td class="col-authors" title="${escapeHtml(authorsStr)}">${escapeHtml(authorsStr)}</td>
        <td class="col-year">${escapeHtml(yearStr)}</td>
        <td class="col-area" title="${escapeHtml(areaStr)}">${escapeHtml(areaStr)}</td>
        <td class="col-type">${escapeHtml(typeStr)}</td>
        <td class="col-confidence">${escapeHtml(confStr)}</td>
      </tr>`;
    }

    el.docTableBody.innerHTML = html;

    // Adicionar eventos de clique nas linhas
    el.docTableBody.querySelectorAll('tr').forEach(row => {
      row.addEventListener('click', () => {
        const path = row.getAttribute('data-path');
        selectItem(path);
      });
    });
  }

  // --- Renderizador de Pill Badges Semânticos ---
  function renderStatusPill(status) {
    switch (status) {
      case 'organized':
        return `<span class="status-pill pill-organized">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>
          Organizado
        </span>`;
      case 'manual_review':
        return `<span class="status-pill pill-review">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
          Revisão
        </span>`;
      case 'duplicate_skipped':
        return `<span class="status-pill pill-duplicate">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
          Duplicata
        </span>`;
      case 'processing':
        return `<span class="status-pill pill-processing">
          <svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="1 4 1 10 7 10"></polyline><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path></svg>
          Processando
        </span>`;
      case 'ignored_non_pdf':
        return `<span class="status-pill pill-ignored">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"></line></svg>
          Ignorado
        </span>`;
      case 'error':
        return `<span class="status-pill pill-error">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"></polygon><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>
          Erro
        </span>`;
      case 'obsolete':
        return `<span class="status-pill pill-obsolete">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"></line></svg>
          Obsoleto
        </span>`;
      default:
        return `<span class="status-pill pill-processing">${escapeHtml(status || 'Pendente')}</span>`;
    }
  }

  // --- Seleção de Item & Renderização do Inspetor ---
  function selectItem(path) {
    state.selectedPath = path;
    const item = state.items.find(i => i.source_path === path);

    // Destacar linha na tabela
    el.docTableBody.querySelectorAll('tr').forEach(r => {
      r.classList.toggle('selected', r.getAttribute('data-path') === path);
    });

    if (!item) {
      el.inspectorEmpty.style.display = 'flex';
      el.inspectorContent.style.display = 'none';
      return;
    }

    renderInspector(item);
  }

  function renderInspector(item) {
    el.inspectorEmpty.style.display = 'none';
    el.inspectorContent.style.display = 'flex';

    // Badge do topo do Inspetor
    const confPct = Math.round((item.confidence || 0) * 100);
    if (item.status === 'organized') {
      el.inspStatusBadge.className = 'status-pill-lg pill-organized';
      el.inspStatusIcon.textContent = '✔';
      el.inspStatusText.textContent = `Organizado (${confPct}% Confiança)`;
      el.inspAbntCard.style.display = 'block';
      el.inspTriageCard.style.display = 'none';
    } else if (item.status === 'manual_review' || item.status === 'error') {
      el.inspStatusBadge.className = 'status-pill-lg pill-review';
      el.inspStatusIcon.textContent = '⚠';
      el.inspStatusText.textContent = item.status === 'error' ? 'Erro de Processamento' : 'Pendente de Revisão Manual';
      el.inspAbntCard.style.display = 'none';
      el.inspTriageCard.style.display = 'block';
      populateTriageForm(item);
    } else if (item.status === 'obsolete') {
      el.inspStatusBadge.className = 'status-pill-lg pill-obsolete';
      el.inspStatusIcon.textContent = '🗄️';
      el.inspStatusText.textContent = 'Obsoleto';
      el.inspAbntCard.style.display = 'none';
      el.inspTriageCard.style.display = 'none';
    } else {
      el.inspStatusBadge.className = 'status-pill-lg pill-duplicate';
      el.inspStatusIcon.textContent = '⧉';
      el.inspStatusText.textContent = item.status === 'duplicate_skipped' ? 'Duplicata Exata' : 'Documento Ignorado';
      el.inspAbntCard.style.display = 'none';
      el.inspTriageCard.style.display = 'none';
    }

    // Citação ABNT NBR 6023
    const citation = buildAbntCitation(item);
    el.inspAbntCitation.innerHTML = citation;

    // Metadados CAPES/CNPq
    el.kvGrandeArea.textContent = item.grande_area || '—';
    el.kvAreaBasica.textContent = item.area_basica || '—';
    el.kvSubarea.textContent = item.subarea || '—';
    el.kvEspecialidade.textContent = item.especialidade || '—';
    el.kvTipo.textContent = item.tipo || '—';
    el.kvConfianca.textContent = item.confidence ? `${(item.confidence * 100).toFixed(0)}%` : '—';
    el.kvOrigem.textContent = getFilename(item.source_path);
    el.kvOrigem.title = item.source_path;
    el.kvDestino.textContent = item.destination_path ? getFilename(item.destination_path) : '—';
    el.kvDestino.title = item.destination_path || '';
    el.kvSha256.textContent = item.sha256 ? item.sha256.substring(0, 16) + '...' : '—';
    el.kvSha256.title = item.sha256 || '';

    // Tooltips e contexto dos botões de ação (priorizando destino)
    if (item.destination_path) {
      el.btnOpenPdf.title = `Abrir PDF organizado (${getFilename(item.destination_path)})`;
      el.btnRevealFolder.title = 'Revelar pasta de destino no Finder / Gerenciador de Arquivos';
    } else {
      el.btnOpenPdf.title = 'Abrir PDF de origem no leitor padrão';
      el.btnRevealFolder.title = 'Revelar pasta de origem no Finder / Gerenciador de Arquivos';
    }
  }

  // --- Formulário de Triagem Manual ---
  function formatTriageError(rawMessage) {
    if (!rawMessage) return 'Encaminhado para validação humana.';
    const raw = String(rawMessage);
    const msg = raw.toLowerCase();

    // Detectar provedor de IA envolvido
    let prov = '';
    if (msg.includes('deepseek')) prov = 'DeepSeek';
    else if (msg.includes('groq')) prov = 'Groq';
    else if (msg.includes('nvidia') || msg.includes('nvapi')) prov = 'NVIDIA';
    else if (msg.includes('claude') || msg.includes('anthropic')) prov = 'Claude';
    else if (msg.includes('gemini') || msg.includes('google')) prov = 'Gemini';

    const provSuffix = prov ? ` no provedor ${prov}` : '';

    if (msg.includes('401') || msg.includes('unauthorized') || msg.includes('não autorizada')) {
      return `Chave de API não autorizada ou expirada${provSuffix}. Por favor, verifique suas credenciais na tela de Preferências.`;
    }
    if (msg.includes('429') || msg.includes('resource_exhausted') || msg.includes('quota') || msg.includes('rate limit')) {
      return `Cota de requisições por minuto ou limite diário excedido${provSuffix}.`;
    }
    if (msg.includes('503') || msg.includes('502') || msg.includes('504') || msg.includes('529') || msg.includes('service unavailable')) {
      return `Instabilidade temporária nos servidores${provSuffix}. Tente novamente mais tarde.`;
    }
    if (msg.includes('timeout') || msg.includes('timed out') || msg.includes('tempo limite')) {
      return `Tempo limite de resposta esgotado ao consultar o provedor${prov ? ' ' + prov : ''}.`;
    }
    if (msg.includes('parse') || msg.includes('json') || msg.includes('inválido') || msg.includes('inválida')) {
      return `Resposta em formato inesperado retornada pela IA${provSuffix}. Não foi possível interpretar a classificação.`;
    }
    return raw;
  }

  function buildTriageAreaOptionsHtml(selectedValue) {
    // Montar optgroups/options da Área Básica com escapeHtml para prevenir XSS via innerHTML
    let abOptions = '';
    for (const [ga, basicas] of Object.entries(CAPES_TAXONOMY)) {
      abOptions += `<optgroup label="${escapeHtml(ga)}">`;
      for (const ab of basicas) {
        const isSel = (ab === selectedValue) ? 'selected' : '';
        abOptions += `<option value="${escapeHtml(ab)}" ${isSel}>${escapeHtml(ab)}</option>`;
      }
      abOptions += `</optgroup>`;
    }
    return abOptions;
  }

  function populateTriageForm(item) {
    el.inspTriageReason.textContent = formatTriageError(item.error_message || item.reasoning) || 'Encaminhado para validação humana.';

    // Popular Área Básica com optgroups por Grande Área (XSS-safe via escapeHtml)
    el.triageAreaBasica.innerHTML = buildTriageAreaOptionsHtml(item.area_basica);
    if (item.area_basica) {
      el.triageAreaBasica.value = item.area_basica;
    }

    // Popular Área Específica (Subárea)
    const initialSubarea = (item.subarea && item.subarea !== 'Geral') ? item.subarea : '';
    if (el.triageSubarea) {
      el.triageSubarea.value = initialSubarea;
    }

    el.triageTitle.value = item.title || getFilename(item.source_path).replace(/\.pdf$/i, '');
    el.triageSubtitle.value = item.subtitle || '';
    el.triageAuthors.value = (item.authors || []).join('; ');
    el.triageYear.value = item.year || '';
    if (item.tipo) el.triageTipo.value = item.tipo;
  }

  el.btnApproveTriage.addEventListener('click', () => {
    if (!state.selectedPath) return;
    const item = state.items.find(i => i.source_path === state.selectedPath);
    const selectedAreaBasica = el.triageAreaBasica ? el.triageAreaBasica.value : (item ? item.area_basica : 'Outros');
    const resolvedGrandeArea = AREA_TO_GRANDE_AREA[selectedAreaBasica] || (item ? item.grande_area : 'Outros');
    const subareaVal = (el.triageSubarea && el.triageSubarea.value.trim()) || (item && item.subarea && item.subarea !== 'Geral' ? item.subarea : 'Geral');

    const triageData = {
      source_path: state.selectedPath,
      destination_path: item ? item.destination_path : null,
      sha256: item ? item.sha256 : '',
      grande_area: resolvedGrandeArea,
      area_basica: selectedAreaBasica,
      subarea: subareaVal,
      tipo: el.triageTipo.value,
      title: el.triageTitle.value.trim(),
      subtitle: el.triageSubtitle.value.trim(),
      authors: el.triageAuthors.value.split(';').map(s => s.trim()).filter(Boolean),
      year: el.triageYear.value ? parseInt(el.triageYear.value, 10) : null,
    };

    if (backend && backend.approveManualTriage) {
      backend.approveManualTriage(JSON.stringify(triageData)).then(resStr => {
        try {
          const res = typeof resStr === 'string' ? JSON.parse(resStr) : resStr;
          if (!res || !res.success) {
            const errMsg = res && res.error ? res.error : 'Não foi possível materializar o item na biblioteca. Verifique se a pasta de destino está acessível e se os campos taxonômicos são válidos.';
            alert('Erro na triagem manual:\n' + errMsg);
          } else {
            console.log('Triagem manual aprovada e materializada com sucesso!');
          }
        } catch (e) {
          console.error('Erro ao processar resposta de triagem:', e);
          alert('Não foi possível materializar o item na biblioteca. Verifique se a pasta de destino está acessível e se os campos taxonômicos são válidos.');
        }
      });
    } else {
      // Simulação local
      const item = state.items.find(i => i.source_path === state.selectedPath);
      if (item) {
        Object.assign(item, triageData, { status: 'organized', confidence: 1.0 });
        updateCounters();
        updateTaxonomyTree();
        renderTable();
        renderInspector(item);
      }
    }
  });

  // --- Citação ABNT NBR 6023 Completa ---
  function formatAbntAuthors(authors) {
    if (!authors || authors.length === 0) return '';
    const formatted = authors.map(a => {
      a = a.trim();
      if (!a) return '';
      if (a.includes(',')) {
        const parts = a.split(',');
        return `${parts[0].trim().toUpperCase()}, ${parts[1].trim()}`;
      }
      const parts = a.split(' ');
      if (parts.length === 1) return parts[0].toUpperCase();
      const last = parts[parts.length - 1].toUpperCase();
      const first = parts.slice(0, -1).join(' ');
      return `${last}, ${first}`;
    }).filter(Boolean);

    if (formatted.length === 0) return '';
    if (formatted.length === 1) return formatted[0];
    if (formatted.length === 2) return `${formatted[0]}; ${formatted[1]}`;
    if (formatted.length === 3) return `${formatted[0]}; ${formatted[1]}; ${formatted[2]}`;
    return `${formatted[0]} et al.`;
  }

  function buildAbntCitation(item) {
    const authors = formatAbntAuthors(item.authors);
    const title = (item.title || getFilename(item.source_path)).trim();
    const subtitle = item.subtitle ? `: ${item.subtitle.trim()}` : '';
    let edition = '';
    if (item.edition) {
      let edStr = String(item.edition).trim().replace(/\b(?:ed|edicao|edição)\.?$/i, '').trim().replace(/\.+$/, '');
      if (edStr) edition = `${edStr}. ed.`;
    }
    const city = item.city || '';
    const publisher = item.publisher || '';
    const journalName = item.journal_name || '';
    const volume = item.volume || '';
    const number = item.number || '';
    const year = item.year ? String(item.year) : 's.d.';
    const pages = item.pages ? (String(item.pages).match(/^\d+$/) ? `${item.pages} p.` : item.pages) : '';
    const doiRaw = item.doi ? String(item.doi) : '';
    const doiUrl = doiRaw && (doiRaw.startsWith('http://') || doiRaw.startsWith('https://') || doiRaw.startsWith('10.'))
      ? (doiRaw.startsWith('http') ? doiRaw : `https://doi.org/${doiRaw}`)
      : '';
    const doiText = doiRaw ? escapeHtml(doiRaw) : '';
    const isbn = item.isbn ? String(item.isbn) : '';
    const tipo = item.tipo || '';

    let parts = [];
    if (authors) {
      // ABNT NBR 6023: Autores em texto normal (sobrenome em caixa alta, sem negrito)
      parts.push(escapeHtml(authors));
    }

    if (tipo === 'Artigo' && journalName) {
      // Artigo: Título normal, Periódico em negrito puro
      const artTitle = `${escapeHtml(title)}${escapeHtml(subtitle)}`;
      parts.push(artTitle);

      let jParts = [`<strong>${escapeHtml(journalName)}</strong>`];
      if (city) jParts.push(escapeHtml(city));
      if (volume) {
        const vStr = String(volume).toLowerCase().startsWith('v.') ? volume : `v. ${volume}`;
        jParts.push(escapeHtml(vStr));
      }
      if (number) {
        const nStr = String(number).toLowerCase().startsWith('n.') ? number : `n. ${number}`;
        jParts.push(escapeHtml(nStr));
      }
      if (pages) {
        const pStr = String(pages).toLowerCase().startsWith('p.') ? pages : `p. ${pages}`;
        jParts.push(escapeHtml(pStr));
      }
      jParts.push(escapeHtml(year));
      parts.push(jParts.join(', '));
    }
    else if (tipo === 'Revista' || tipo === 'Revista Científica') {
      // Revista / Revista Científica — NBR 6023:2025 7.7.3
      parts = [];
      const journalTitle = `<strong>${escapeHtml(String(journalName || title).toUpperCase())}</strong>`;
      const journalParts = [journalTitle];
      if (city) journalParts.push(escapeHtml(city));
      if (publisher) journalParts.push(escapeHtml(publisher));
      if (year) journalParts.push(escapeHtml(year));
      // rotulo_volume / volume_label diferenciam 'ano X' de 'v. X'
      const volLabel = String(item.rotulo_volume || item.volume_label || '').trim().toLowerCase();
      if (volume) {
        const vStr = volLabel.startsWith('ano') ? `ano ${volume}` : (String(volume).toLowerCase().startsWith('v.') ? volume : `v. ${volume}`);
        journalParts.push(escapeHtml(vStr));
      }
      // publication_month ?? item.month
      const publicationMonth = item.publication_month ?? item.month;
      const mesPT = {1:'jan.',2:'fev.',3:'mar.',4:'abr.',5:'mai.',6:'jun.',7:'jul.',8:'ago.',9:'set.',10:'out.',11:'nov.',12:'dez.'};
      if (publicationMonth) {
        const m = parseInt(String(publicationMonth), 10);
        if (!isNaN(m) && m >= 1 && m <= 12) journalParts.push(mesPT[m]);
      }
      if (number) {
        const nStr = String(number).toLowerCase().startsWith('n.') ? number : `n. ${number}`;
        journalParts.push(escapeHtml(nStr));
      }
      // supplement vs issue_designation/designacao_fasciculo/designation.
      // Suprime designacao quando redundante com number (removendo prefixos
      // n., n°, nº, no., numero, # e zeros a esquerda). Mantem 'Edicao Especial',
      // 'Suplemento', 'N° 0'.
      const isSupplement = Boolean(item.supplement);
      const designation = item.supplement || item.issue_designation || item.designacao_fasciculo || item.designação || item.designation;
      let designationToShow = designation;
      if (designation && !isSupplement && number) {
        const normNum = String(number).replace(/^(n\.?|n°|nº|no\.?|numero|#)\s*/i, '').replace(/^0+/, '') || '0';
        const normDesig = String(designation).replace(/^(n\.?|n°|nº|no\.?|numero|#)\s*/i, '').replace(/^0+/, '') || '0';
        if (normDesig !== '0' && normDesig === normNum) {
          designationToShow = null;
        }
      }
      if (designationToShow) journalParts.push(escapeHtml(designationToShow));
      parts.push(journalParts.join(', '));
    } else {
      // Livro ou Outros: Título principal em negrito puro, subtítulo normal
      const bookTitle = `<strong>${escapeHtml(title)}</strong>${escapeHtml(subtitle)}`;
      parts.push(bookTitle);

      if (edition) parts.push(escapeHtml(edition));

      // Cidade : Editora, Ano
      let imprint = '';
      if (city && publisher) {
        imprint = `${city}: ${publisher}`;
      } else if (publisher) {
        imprint = `[S.l.]: ${publisher}`;
      } else if (city) {
        imprint = `${city}: [s.n.]`;
      }

      if (imprint) {
        imprint += `, ${year}`;
      } else {
        imprint = year;
      }
      parts.push(escapeHtml(imprint));

      if (pages) parts.push(escapeHtml(pages));
    }

    // Limpar pontos e juntar
    const cleanParts = parts.map(p => p.trim().replace(/\.+$/, '')).filter(Boolean);
    let citation = cleanParts.join('. ') + '.';
    if (doiUrl) citation += ` Disponível em: <a href="${escapeHtml(doiUrl)}" target="_blank">${escapeHtml(doiUrl)}</a>.`;
    else if (doiText) citation += ` Disponível em: ${doiText}.`;
    if (isbn) citation += ` ISBN ${escapeHtml(isbn)}.`;

    return citation;
  }

  function fallbackCopyText(text) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    ta.style.top = '-9999px';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
    } catch (_) {}
    document.body.removeChild(ta);
  }

  function convertCitationHtmlToMarkdown(html) {
    if (!html) return '';
    return html
      .replace(/<strong>(.*?)<\/strong>/gi, '**$1**')
      .replace(/<b>(.*?)<\/b>/gi, '**$1**')
      .replace(/<a\s+href="([^"]+)"[^>]*>(.*?)<\/a>/gi, '$1')
      .replace(/<[^>]+>/g, '')
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .trim();
  }

  el.btnCopyCitation.addEventListener('click', () => {
    const htmlText = el.inspAbntCitation.innerHTML;
    const markdownText = convertCitationHtmlToMarkdown(htmlText) || el.inspAbntCitation.innerText;

    function showCopied() {
      const orig = el.btnCopyCitation.innerHTML;
      el.btnCopyCitation.innerHTML = '✔ Copiado com Formatação!';
      setTimeout(() => { el.btnCopyCitation.innerHTML = orig; }, 1800);
    }

    // Tentar cópia com formatação HTML nativa e Markdown via evento 'copy'
    let copied = false;
    const onCopy = function (e) {
      e.clipboardData.setData('text/html', `<!DOCTYPE html><html><body>${htmlText}</body></html>`);
      e.clipboardData.setData('text/plain', markdownText);
      e.preventDefault();
      copied = true;
    };
    document.addEventListener('copy', onCopy);
    try {
      document.execCommand('copy');
    } catch (_) {}
    document.removeEventListener('copy', onCopy);

    if (copied) {
      showCopied();
      return;
    }

    // Fallback: Clipboard API do navegador
    if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {
      const blobText = new Blob([markdownText], { type: 'text/plain' });
      const blobHtml = new Blob([`<html><body>${htmlText}</body></html>`], { type: 'text/html' });
      const item = new ClipboardItem({
        'text/plain': blobText,
        'text/html': blobHtml,
      });
      navigator.clipboard.write([item]).then(showCopied).catch(() => {
        if (backend && backend.copyToClipboard) {
          backend.copyToClipboard(markdownText);
        } else {
          fallbackCopyText(markdownText);
        }
        showCopied();
      });
      return;
    }

    // Fallback seguro: backend Python (com sintaxe Markdown para preservar negrito em texto puro)
    if (backend && backend.copyToClipboard) {
      backend.copyToClipboard(markdownText);
    } else {
      fallbackCopyText(markdownText);
    }
    showCopied();
  });

  // --- Controles de Operação & Ações ---
  el.btnBrowseSource.addEventListener('click', () => {
    if (backend && backend.browseSource) {
      backend.browseSource().then(path => { if (path) setSource(path); });
    }
  });

  el.btnBrowseTarget.addEventListener('click', () => {
    if (backend && backend.browseTarget) {
      backend.browseTarget().then(path => { if (path) setTarget(path); });
    }
  });

  function setSource(path) {
    state.sourceDir = path;
    el.sourcePath.textContent = path || '—';
    el.sourcePath.title = path || '';
  }

  function setTarget(path) {
    state.targetDir = path;
    el.targetPath.textContent = path || '—';
    el.targetPath.title = path || '';
  }

  // Nome amigável de cada provedor para exibição no indicador de chave
  const PROVIDER_LABELS = {
    gemini: 'Gemini',
    groq: 'Groq — Fallback',
    nvidia: 'NVIDIA NIM',
    claude: 'Anthropic Claude',
    deepseek: 'DeepSeek',
  };

  function providerLabel() {
    return PROVIDER_LABELS[state.provider] || state.provider;
  }

  function updateKeyBadge(hasKey, provider) {
    if (provider) state.provider = provider;
    if (backend && backend.getProviderKeyStatus && state.provider) {
      backend.getProviderKeyStatus(state.provider).then(function(status) {
        const label = providerLabel();
        if (status === 'valid') {
          el.keyBadge.className = 'badge-pill badge-key-active';
          el.keyBadgeText.textContent = label + ' — Chave Configurada';
        } else if (status === 'invalid') {
          el.keyBadge.className = 'badge-pill badge-key-error';
          el.keyBadgeText.textContent = label + ' — Chave Inválida';
        } else {
          el.keyBadge.className = 'badge-pill badge-key-simulated';
          el.keyBadgeText.textContent = label + ' — Sem chave (Modo Simulado)';
        }
      });
      return;
    }
    const label = providerLabel();
    if (hasKey) {
      el.keyBadge.className = 'badge-pill badge-key-active';
      el.keyBadgeText.textContent = label + ' — Chave Configurada';
    } else {
      el.keyBadge.className = 'badge-pill badge-key-simulated';
      el.keyBadgeText.textContent = label + ' — Sem chave (Modo Simulado)';
    }
  }

  // Segmented Mode (Copiar / Mover)
  el.btnModeCopy.addEventListener('click', () => {
    state.fileOperation = 'copy';
    el.btnModeCopy.classList.add('active');
    el.btnModeMove.classList.remove('active');
  });

  el.btnModeMove.addEventListener('click', () => {
    state.fileOperation = 'move';
    el.btnModeMove.classList.add('active');
    el.btnModeCopy.classList.remove('active');
  });

  // Checkboxes
  el.chkRecursive.addEventListener('change', e => { state.recursive = e.target.checked; });
  el.chkDryRun.addEventListener('change', e => { state.dryRun = e.target.checked; });
  el.modelSelect.addEventListener('change', e => {
    state.provider = e.target.value;
    if (backend && backend.checkProviderKey) {
      backend.checkProviderKey(state.provider).then(function (hasKey) {
        updateKeyBadge(hasKey, state.provider);
      });
    } else {
      updateKeyBadge(false, state.provider);
    }
  });

  // Botão Organizar Acervo / Interromper
  el.btnOrganize.addEventListener('click', () => {
    if (state.isRunning) {
      // Interromper
      if (backend && backend.cancelPipeline) {
        backend.cancelPipeline();
        el.organizeLabel.textContent = 'Finalizando estágio atual...';
        el.btnOrganize.disabled = true;
      }
    } else {
      // Validar pastas
      if (!state.sourceDir) {
        alert('Por favor, selecione a pasta de Origem.');
        return;
      }
      if (!state.targetDir) {
        alert('Por favor, selecione a pasta de Destino.');
        return;
      }

      state.isRunning = true;
      state.batchStartTime = Date.now();
      if (el.avgTimeIndicator) el.avgTimeIndicator.textContent = 'média por arquivo: Calculando...';
      if (el.etaIndicator) el.etaIndicator.textContent = 'Total estimado: Calculando...';
      state.items = []; // Limpar lote anterior
      state.selectedPath = null;
      closeCompletionModal();
      if (el.completionBanner) el.completionBanner.style.display = 'none';
      renderTable();
      updateCounters();
      updateOrganizeButton();

      const params = {
        source_dir: state.sourceDir,
        target_dir: state.targetDir,
        provider: state.provider,
        file_operation: state.fileOperation,
        recursive: state.recursive,
        dry_run: state.dryRun,
      };

      if (backend && backend.startOrganize) {
        backend.startOrganize(JSON.stringify(params));
      }
    }
  });

  function updateOrganizeButton() {
    el.btnOrganize.disabled = false;
    if (state.isRunning) {
      el.btnOrganize.className = 'btn btn-danger';
      el.organizeLabel.textContent = 'Interromper Lote';
      el.organizeIcon.innerHTML = '<rect x="6" y="6" width="12" height="12"></rect>';
      setBatchControlsDisabled(true);
    } else {
      el.btnOrganize.className = 'btn btn-primary';
      el.organizeLabel.textContent = 'Organizar Acervo';
      el.organizeIcon.innerHTML = '<polygon points="5 3 19 12 5 21 5 3"></polygon>';
      setBatchControlsDisabled(false);
    }
  }

  function setBatchControlsDisabled(disabled) {
    if (el.modelSelect) el.modelSelect.disabled = disabled;
    if (el.btnBrowseSource) el.btnBrowseSource.disabled = disabled;
    if (el.btnBrowseTarget) el.btnBrowseTarget.disabled = disabled;
    if (el.btnModeCopy) el.btnModeCopy.disabled = disabled;
    if (el.btnModeMove) el.btnModeMove.disabled = disabled;
    if (el.chkRecursive) el.chkRecursive.disabled = disabled;
    if (el.chkDryRun) el.chkDryRun.disabled = disabled;
    if (el.btnPreferences) el.btnPreferences.disabled = disabled;
    if (el.btnCache) el.btnCache.disabled = disabled;
  }

  // Botões de Rodapé do Inspetor (Priorizando o arquivo e pasta de destino)
  el.btnOpenPdf.addEventListener('click', () => {
    if (!state.selectedPath) return;
    const item = state.items.find(i => i.source_path === state.selectedPath);
    // Prioriza o arquivo organizado de destino; se ainda não materializado, abre a origem
    const targetPath = (item && item.destination_path) ? item.destination_path : state.selectedPath;
    if (backend && backend.openPdf) {
      backend.openPdf(targetPath);
    }
  });

  el.btnRevealFolder.addEventListener('click', () => {
    if (!state.selectedPath) return;
    const item = state.items.find(i => i.source_path === state.selectedPath);
    // Prioriza o local de destino no Finder / Gerenciador de arquivos
    const targetPath = (item && item.destination_path) ? item.destination_path : state.selectedPath;
    if (backend && backend.revealPath) {
      backend.revealPath(targetPath);
    }
  });

  // Preferências e Cache
  el.btnPreferences.addEventListener('click', () => {
    if (backend && backend.openPreferences) backend.openPreferences();
  });
  el.btnCache.addEventListener('click', () => {
    if (backend && backend.openCacheDialog) backend.openCacheDialog();
  });

  // Desativar menu de contexto de navegador (Back, Reload, View Source)
  document.addEventListener('contextmenu', e => {
    if (!['INPUT', 'TEXTAREA'].includes(e.target.tagName)) {
      e.preventDefault();
    }
  });

  // Filtros da Barra Lateral (Precedência sobre a árvore CAPES e reset global)
  el.filterList.querySelectorAll('.filter-item').forEach(item => {
    item.addEventListener('click', () => {
      el.filterList.querySelectorAll('.filter-item').forEach(i => i.classList.remove('active'));
      item.classList.add('active');
      state.activeFilter = item.getAttribute('data-filter');
      // Precedência de status: limpa qualquer filtro ativo de subárvore CAPES para evitar combinações vazias
      state.activeAreaFilter = null;
      updateTaxonomyTree();
      renderTable();
    });
  });

  // Busca Instantânea
  el.searchInput.addEventListener('input', e => {
    state.searchQuery = e.target.value;
    el.btnClearSearch.style.display = state.searchQuery ? 'block' : 'none';
    renderTable();
  });

  el.btnClearSearch.addEventListener('click', () => {
    el.searchInput.value = '';
    state.searchQuery = '';
    el.btnClearSearch.style.display = 'none';
    renderTable();
    el.searchInput.focus();
  });

  // --- Limpeza da Tela para Novo Lote ---
  function clearScreenForNewBatch() {
    closeCompletionModal();
    state.items = [];
    state.selectedPath = null;
    state.activeFilter = 'all';
    state.activeAreaFilter = null;
    state.searchQuery = '';
    el.searchInput.value = '';
    if (el.btnClearSearch) el.btnClearSearch.style.display = 'none';
    if (el.completionBanner) el.completionBanner.style.display = 'none';

    // Reset status bar
    el.progressBarFill.style.width = '0%';
    el.progressPct.textContent = '0%';
    el.stageIndicator.textContent = 'Estágio: Ocioso';
    el.countIndicator.textContent = '0 / 0 processados';
    el.remainingIndicator.textContent = 'Restam: 0';
    el.qualityMetric.className = 'quality-metric badge-gray';
    el.qualityMetric.textContent = 'Revisão Manual: 0,0%';

    // Reset indicadores de tempo
    if (el.avgTimeIndicator) el.avgTimeIndicator.textContent = '—';
    if (el.etaIndicator) el.etaIndicator.textContent = '—';
    state.batchStartTime = null;

    // Reset filtros na barra lateral
    el.filterList.querySelectorAll('.filter-item').forEach(i => i.classList.remove('active'));
    const allFilterItem = el.filterList.querySelector('[data-filter="all"]');
    if (allFilterItem) allFilterItem.classList.add('active');

    updateCounters();
    updateTaxonomyTree();
    renderTable();
    renderInspector(null);
  }

  if (el.btnClearBatch) {
    el.btnClearBatch.addEventListener('click', (e) => {
      e.stopPropagation();
      clearScreenForNewBatch();
    });
  }
  if (el.completionBanner) {
    el.completionBanner.addEventListener('click', () => {
      clearScreenForNewBatch();
    });
  }

  // --- Eventos do Modal Popup de Conclusão ---
  if (el.btnModalClose) {
    el.btnModalClose.addEventListener('click', closeCompletionModal);
  }
  if (el.btnModalReview) {
    el.btnModalReview.addEventListener('click', () => {
      closeCompletionModal();
      if (state.items.length > 0 && !state.selectedPath) {
        selectItem(state.items[0].source_path);
      }
    });
  }
  if (el.btnModalClear) {
    el.btnModalClear.addEventListener('click', () => {
      closeCompletionModal();
      clearScreenForNewBatch();
    });
  }
  if (el.completionModal) {
    el.completionModal.addEventListener('click', (e) => {
      if (e.target === el.completionModal) {
        closeCompletionModal();
      }
    });
  }
  // --- Eventos do Modal "Sobre o Tomus" ---
  function openAboutModal() {
    if (el.aboutModal) {
      el.aboutModal.style.display = 'flex';
    }
  }

  function closeAboutModal() {
    if (el.aboutModal) {
      el.aboutModal.style.display = 'none';
    }
  }

  if (el.btnAbout) {
    el.btnAbout.addEventListener('click', openAboutModal);
  }
  if (el.btnAboutClose) {
    el.btnAboutClose.addEventListener('click', closeAboutModal);
  }
  if (el.btnAboutOk) {
    el.btnAboutOk.addEventListener('click', closeAboutModal);
  }
  if (el.aboutModal) {
    el.aboutModal.addEventListener('click', (e) => {
      if (e.target === el.aboutModal) {
        closeAboutModal();
      }
    });
  }

  // Copiar chave Pix
  if (el.btnCopyPix && el.pixKeyInput) {
    el.btnCopyPix.addEventListener('click', () => {
      const pix = el.pixKeyInput.value.trim();
      navigator.clipboard.writeText(pix).then(() => {
        const orig = el.btnCopyPix.innerHTML;
        el.btnCopyPix.innerHTML = '✔ Copiado!';
        setTimeout(() => { el.btnCopyPix.innerHTML = orig; }, 1800);
      });
    });
  }

  // Links externos no Modal Sobre
  document.querySelectorAll('.link-external').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const url = link.getAttribute('data-url');
      if (backend && backend.openExternalUrl) {
        backend.openExternalUrl(url);
      } else {
        window.open(url, '_blank');
      }
    });
  });

  // --- Redimensionadores de Painéis (Splitters Laterais) ---
  const mainContent = document.querySelector('.main-content');
  const sidebarPanel = document.getElementById('sidebarPanel');
  const inspectorPanel = document.getElementById('inspectorPanel');
  const sidebarResizer = document.getElementById('sidebarResizer');
  const tableResizer = document.getElementById('tableResizer');

  let currentSidebarWidth = 260;
  let currentInspectorWidth = 370;

  function updateMainGrid() {
    if (mainContent) {
      mainContent.style.gridTemplateColumns = `${currentSidebarWidth}px 8px 1fr 8px ${currentInspectorWidth}px`;
    }
  }

  // Splitter 1: Barra Lateral (Esquerda)
  if (sidebarResizer && sidebarPanel && mainContent) {
    let isDragging = false;
    let startX = 0;
    let startWidth = currentSidebarWidth;

    sidebarResizer.addEventListener('mousedown', (e) => {
      isDragging = true;
      startX = e.clientX;
      startWidth = sidebarPanel.getBoundingClientRect().width;
      sidebarResizer.classList.add('is-dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      const dx = e.clientX - startX; // arrastar para direita expande a barra lateral
      currentSidebarWidth = Math.max(180, Math.min(500, startWidth + dx));
      updateMainGrid();
    });

    document.addEventListener('mouseup', () => {
      if (!isDragging) return;
      isDragging = false;
      sidebarResizer.classList.remove('is-dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    });
  }

  // Splitter 2: Painel de Inspeção (Direita)
  if (tableResizer && inspectorPanel && mainContent) {
    let isDragging = false;
    let startX = 0;
    let startWidth = currentInspectorWidth;

    tableResizer.addEventListener('mousedown', (e) => {
      isDragging = true;
      startX = e.clientX;
      startWidth = inspectorPanel.getBoundingClientRect().width;
      tableResizer.classList.add('is-dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      const dx = startX - e.clientX; // arrastar para esquerda expande o painel direito
      currentInspectorWidth = Math.max(280, Math.min(680, startWidth + dx));
      updateMainGrid();
    });

    document.addEventListener('mouseup', () => {
      if (!isDragging) return;
      isDragging = false;
      tableResizer.classList.remove('is-dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    });
  }

  // --- Redimensionadores de Colunas da Tabela ---
  function initTableColumnResizers() {
    const table = document.getElementById('docTable');
    if (!table) return;
    const ths = table.querySelectorAll('th');

    ths.forEach(th => {
      const resizer = th.querySelector('.th-resizer');
      if (!resizer) return;

      let isResizing = false;
      let startX = 0;
      let startWidth = 0;

      resizer.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        e.preventDefault();
        isResizing = true;
        startX = e.clientX;

        // Congelar larguras atuais em px de todas as colunas antes de alterar qualquer estilo
        const currentWidths = Array.from(ths).map(h => h.getBoundingClientRect().width);
        let totalInitialWidth = 0;
        ths.forEach((h, idx) => {
          const w = currentWidths[idx];
          totalInitialWidth += w;
          const wPx = `${w}px`;
          h.style.width = wPx;
          h.style.minWidth = wPx;
          h.style.maxWidth = wPx;
        });

        startWidth = th.getBoundingClientRect().width;
        table.style.minWidth = '0';
        table.style.width = `${totalInitialWidth}px`;

        resizer.classList.add('is-resizing');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';

        function onMouseMove(moveEvent) {
          if (!isResizing) return;
          const diffX = moveEvent.clientX - startX;
          const newWidth = Math.max(36, startWidth + diffX);
          const newWidthPx = `${newWidth}px`;
          th.style.width = newWidthPx;
          th.style.minWidth = newWidthPx;
          th.style.maxWidth = newWidthPx;

          let totalWidth = 0;
          ths.forEach(h => {
            totalWidth += parseFloat(h.style.width) || h.getBoundingClientRect().width;
          });
          table.style.minWidth = '0';
          table.style.width = `${totalWidth}px`;
        }

        function onMouseUp() {
          if (!isResizing) return;
          isResizing = false;
          resizer.classList.remove('is-resizing');
          document.body.style.cursor = '';
          document.body.style.userSelect = '';
          document.removeEventListener('mousemove', onMouseMove);
          document.removeEventListener('mouseup', onMouseUp);
        }

        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
      });
    });
  }

  initTableColumnResizers();

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (el.aboutModal && el.aboutModal.style.display === 'flex') {
        closeAboutModal();
      } else if (el.completionModal && el.completionModal.style.display === 'flex') {
        closeCompletionModal();
      }
    }
  });

  // --- Utilitários ---
  function getFilename(path) {
    if (!path) return '';
    return path.replace(/^.*[\\/]/, '');
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Dados Mock para teste no navegador comum
  function setupMockData() {
    setSource('~/Desktop/origem');
    setTarget('~/Desktop/destino_gui');
    state.items = [
      {
        source_path: '/Users/pesquisador/Desktop/origem/Vygotsky - Pensamento e Linguagem.pdf',
        destination_path: '/Users/pesquisador/Desktop/destino_gui/Ciências Humanas/Psicologia/Livro/VYGOTSKY_2003.pdf',
        status: 'organized',
        title: 'Pensamento e Linguagem',
        authors: ['Vygotsky, Lev Semenovitch'],
        year: 2003,
        grande_area: 'Ciências Humanas',
        area_basica: 'Psicologia',
        tipo: 'Livro',
        confidence: 0.98,
        sha256: '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08'
      },
      {
        source_path: '/Users/pesquisador/Desktop/origem/CamScanner_documento.pdf',
        destination_path: '',
        status: 'manual_review',
        title: 'Documento sem título legível',
        authors: ['Autor Desconhecido'],
        year: null,
        grande_area: 'Ciências Humanas',
        area_basica: 'Sociologia',
        tipo: 'Outros',
        confidence: 0.45,
        reasoning: 'O texto extraído contém apenas a marca d\'água \'Scanned with CamScanner\'.',
        sha256: '5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8'
      }
    ];
    updateCounters();
    updateTaxonomyTree();
    renderTable();
    selectItem(state.items[0].source_path);
  }

  // Inicializar quando o DOM estiver pronto
  document.addEventListener('DOMContentLoaded', initWebChannel);

})();
