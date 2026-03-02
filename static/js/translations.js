$(document).ready(function() {
    loadRules();
    // Toggle source field requirements based on rule type
    $('#ruleType').on('change', function() {
        const type = $(this).val();
        const isTranslation = type === 'translation';
        $('#sourceColumn').prop('required', isTranslation);
        $('#sourceValue').prop('required', isTranslation);
        $('#sourceColumn').prop('disabled', !isTranslation);
        $('#sourceValue').prop('disabled', !isTranslation);
    }).trigger('change');

    // Toggle condition section visibility
    $('#toggleConditionBtn').on('click', function() {
        const section = $('#conditionSection');
        const isHidden = section.is(':hidden');
        section.toggle(isHidden);
        $(this).text(isHidden ? 'Bedingung entfernen' : 'Bedingung hinzufügen');
        if (!isHidden) {
            // Clearing values when removing condition
            $('#conditionColumn').val('');
            $('#conditionOperator').val('contains');
            $('#conditionValue').val('');
        }
    });

    // Toggle edit condition section visibility
    $('#toggleEditConditionBtn').on('click', function() {
        const section = $('#editConditionSection');
        const isHidden = section.is(':hidden');
        section.toggle(isHidden);
        $(this).text(isHidden ? 'Bedingung entfernen' : 'Bedingung hinzufügen');
        if (!isHidden) {
            // Clearing values when removing condition
            $('#editConditionColumn').val('');
            $('#editConditionOperator').val('contains');
            $('#editConditionValue').val('');
        }
    });
});

function loadRules() {
    $.get('/rules/list', function(response) {
        if (response.success) {
            displayRules(response.rules || []);
        } else {
            showError('Migrationsregeln konnten nicht geladen werden: ' + response.error);
        }
    }).fail(function(xhr) {
        showError('Migrationsregeln konnten nicht geladen werden: ' + xhr.responseText);
    });
}

function displayRules(rules) {
    const tbody = $('#translationsBody');
    tbody.empty();
    
    if (rules.length === 0) {
        tbody.append('<tr><td colspan="11" class="text-center text-muted">Noch keine Migrationsregeln definiert</td></tr>');
        return;
    }
    
    rules.forEach(function(t) {
        const createdAt = t.created_at ? new Date(t.created_at).toLocaleString() : 'N/A';
        const condition = (t.condition_column && t.condition_value) 
            ? `${escapeHtml(t.condition_column)} ${escapeHtml(t.condition_operator || 'contains')} ${escapeHtml(t.condition_value)}`
            : '-';
        const type = (t.rule_type || 'translation').toLowerCase();
        const typeClass = type === 'overwrite' ? 'badge-warning' : 'badge-info';
        const execOrder = t.execution_order !== undefined ? t.execution_order : 100;
        const row = `
            <tr>
                <td><span class="badge badge-secondary">${execOrder}</span></td>
                <td><span class="badge ${typeClass}">${escapeHtml(t.rule_type || 'translation')}</span></td>
                <td><code>${escapeHtml(t.source_column)}</code></td>
                <td><code>${escapeHtml(t.target_column)}</code></td>
                <td><strong>${escapeHtml(t.source_value)}</strong></td>
                <td><strong>${escapeHtml(t.target_value)}</strong></td>
                <td>${condition}</td>
                <td>${escapeHtml(t.notes || '')}</td>
                <td>${escapeHtml(t.created_by || 'system')}</td>
                <td>${createdAt}</td>
                <td>
                    <i class="fas fa-arrow-up edit-icon" title="Nach oben" onclick="moveRuleUp(${t.id})"></i>
                    <i class="fas fa-arrow-down edit-icon" title="Nach unten" onclick="moveRuleDown(${t.id})"></i>
                    <i class="fas fa-edit edit-icon" title="Bearbeiten" onclick="editRule(${t.id})"></i>
                    <i class="fas fa-copy edit-icon" title="Duplizieren" onclick="cloneRule(${t.id})"></i>
                    <i class="fas fa-trash delete-icon" title="Löschen" onclick="deleteRule(${t.id})"></i>
                </td>
            </tr>
        `;
        tbody.append(row);
    });
}

function saveRule() {
    const data = {
        rule_type: $('#ruleType').val().trim(),
        source_column: $('#sourceColumn').val().trim(),
        target_column: $('#targetColumn').val().trim(),
        source_value: $('#sourceValue').val().trim(),
        target_value: $('#targetValue').val(),  // Keep original value, don't trim to preserve empty strings
        condition_column: $('#conditionColumn').val().trim(),
        condition_operator: $('#conditionOperator').val().trim(),
        condition_value: $('#conditionValue').val().trim(),
        notes: $('#notes').val().trim()
    };
    
    if (data.rule_type === 'translation') {
        if (!data.source_column || !data.target_column || data.target_value === null || data.target_value === undefined) {
            showError('source_column, target_column und target_value sind erforderlich');
            return;
        }
    } else {
        if (!data.target_column || data.target_value === null || data.target_value === undefined) {
            showError('target_column und target_value sind für Überschreibungen erforderlich');
            return;
        }
    }
    
    $.ajax({
        url: '/rules/add',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(data),
        success: function(response) {
            if (response.success) {
                $('#addRuleModal').modal('hide');
                $('#addRuleForm')[0].reset();
                showSuccess('Regel erfolgreich hinzugefügt');
                loadRules();
            } else {
                showError('Regel konnte nicht hinzugefügt werden: ' + response.error);
            }
        },
        error: function(xhr) {
            const error = xhr.responseJSON ? xhr.responseJSON.error : xhr.responseText;
            showError('Regel konnte nicht hinzugefügt werden: ' + error);
        }
    });
}

function editRule(id) {
    // Find the translation in current data
    $.get('/rules/list', function(response) {
        if (response.success) {
            const rule = (response.rules || []).find(t => t.id === id);
            if (rule) {
                $('#editRuleId').val(rule.id);
                $('#editRuleType').val(rule.rule_type);
                $('#editSourceColumn').val(rule.source_column);
                $('#editTargetColumn').val(rule.target_column);
                $('#editSourceValue').val(rule.source_value);
                $('#editTargetValue').val(rule.target_value);
                $('#editConditionColumn').val(rule.condition_column || '');
                $('#editConditionOperator').val(rule.condition_operator || 'contains');
                $('#editConditionValue').val(rule.condition_value || '');
                $('#editNotes').val(rule.notes || '');
                // Disable/enable source fields depending on rule type (overwrite vs translation)
                const isTranslation = (rule.rule_type || 'translation').toLowerCase() === 'translation';
                $('#editSourceColumn').prop('disabled', !isTranslation);
                $('#editSourceValue').prop('disabled', !isTranslation);
                // Show condition section if the rule has a condition
                const hasCondition = !!(rule.condition_column && rule.condition_value);
                $('#editConditionSection').toggle(hasCondition);
                $('#toggleEditConditionBtn').text(hasCondition ? 'Bedingung entfernen' : 'Bedingung hinzufügen');
                $('#editRuleModal').modal('show');
            }
        }
    });
}

function cloneRule(id) {
    // Find the rule and populate Add modal with its data
    $.get('/rules/list', function(response) {
        if (response.success) {
            const rule = (response.rules || []).find(t => t.id === id);
            if (rule) {
                // Populate Add modal with cloned data
                $('#ruleType').val(rule.rule_type || 'translation').trigger('change');
                $('#sourceColumn').val(rule.source_column);
                $('#targetColumn').val(rule.target_column);
                $('#sourceValue').val(rule.source_value);
                $('#targetValue').val(rule.target_value);
                $('#conditionColumn').val(rule.condition_column || '');
                $('#conditionOperator').val(rule.condition_operator || 'contains');
                $('#conditionValue').val(rule.condition_value || '');
                $('#notes').val((rule.notes || '') + ' (cloned)');
                // Show condition section if the rule has a condition
                const hasCondition = !!(rule.condition_column && rule.condition_value);
                $('#conditionSection').toggle(hasCondition);
                $('#toggleConditionBtn').text(hasCondition ? 'Bedingung entfernen' : 'Bedingung hinzufügen');
                $('#addRuleModal').modal('show');
            }
        }
    });
}

function updateRule() {
    const id = $('#editRuleId').val();
    const data = {
        source_column: $('#editSourceColumn').val(),
        target_column: $('#editTargetColumn').val(),
        target_value: $('#editTargetValue').val(),  // Keep original value, don't trim to preserve empty strings
        condition_column: $('#editConditionColumn').val().trim(),
        condition_operator: $('#editConditionOperator').val().trim(),
        condition_value: $('#editConditionValue').val().trim(),
        notes: $('#editNotes').val().trim()
    };
    
    if (data.target_value === null || data.target_value === undefined) {
        showError('Zielwert ist erforderlich');
        return;
    }
    
    $.ajax({
        url: `/rules/${id}/update`,
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(data),
        success: function(response) {
            if (response.success) {
                $('#editRuleModal').modal('hide');
                showSuccess('Regel erfolgreich aktualisiert');
                loadRules();
            } else {
                showError('Regel konnte nicht aktualisiert werden: ' + response.error);
            }
        },
        error: function(xhr) {
            const error = xhr.responseJSON ? xhr.responseJSON.error : xhr.responseText;
            showError('Regel konnte nicht aktualisiert werden: ' + error);
        }
    });
}

function deleteRule(id) {
    if (!confirm('Diese Migrationsregel wirklich löschen?')) {
        return;
    }
    
    $.ajax({
        url: `/rules/${id}/delete`,
        method: 'POST',
        success: function(response) {
            if (response.success) {
                showSuccess('Regel erfolgreich gelöscht');
                loadRules();
            } else {
                showError('Regel konnte nicht gelöscht werden: ' + response.error);
            }
        },
        error: function(xhr) {
            const error = xhr.responseJSON ? xhr.responseJSON.error : xhr.responseText;
            showError('Regel konnte nicht gelöscht werden: ' + error);
        }
    });
}

function moveRuleUp(id) {
    $.ajax({
        url: `/rules/${id}/move_up`,
        method: 'POST',
        success: function(response) {
            if (response.success) {
                loadRules();
            } else {
                showError(response.error || 'Regel konnte nicht verschoben werden');
            }
        },
        error: function(xhr) {
            const error = xhr.responseJSON ? xhr.responseJSON.error : xhr.responseText;
            showError('Regel konnte nicht verschoben werden: ' + error);
        }
    });
}

function moveRuleDown(id) {
    $.ajax({
        url: `/rules/${id}/move_down`,
        method: 'POST',
        success: function(response) {
            if (response.success) {
                loadRules();
            } else {
                showError(response.error || 'Regel konnte nicht verschoben werden');
            }
        },
        error: function(xhr) {
            const error = xhr.responseJSON ? xhr.responseJSON.error : xhr.responseText;
            showError('Regel konnte nicht verschoben werden: ' + error);
        }
    });
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return String(text || '').replace(/[&<>"']/g, function(m) { return map[m]; });
}

function showSuccess(message) {
    alert(message);
}

function showError(message) {
    alert('Fehler: ' + message);
}
