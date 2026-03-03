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
        $(this).text(isHidden ? t('rules.remove_condition') : t('rules.add_condition'));
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
        $(this).text(isHidden ? t('rules.remove_condition') : t('rules.add_condition'));
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
            showError(t('rules.load_error') + ': ' + response.error);
        }
    }).fail(function(xhr) {
        showError(t('rules.load_error') + ': ' + xhr.responseText);
    });
}

function displayRules(rules) {
    const tbody = $('#translationsBody');
    tbody.empty();
    
    if (rules.length === 0) {
        tbody.append('<tr><td colspan="11" class="text-center text-muted">' + t('rules.empty') + '</td></tr>');
        return;
    }
    
    rules.forEach(function(rule) {
        const createdAt = rule.created_at ? new Date(rule.created_at).toLocaleString() : 'N/A';
        const condition = (rule.condition_column && rule.condition_value) 
            ? `${escapeHtml(rule.condition_column)} ${escapeHtml(rule.condition_operator || 'contains')} ${escapeHtml(rule.condition_value)}`
            : '-';
        const type = (rule.rule_type || 'translation').toLowerCase();
        const typeClass = type === 'overwrite' ? 'badge-warning' : 'badge-info';
        const execOrder = rule.execution_order !== undefined ? rule.execution_order : 100;
        const row = `
            <tr>
                <td><span class="badge badge-secondary">${execOrder}</span></td>
                <td><span class="badge ${typeClass}">${escapeHtml(rule.rule_type || 'translation')}</span></td>
                <td><code>${escapeHtml(rule.source_column)}</code></td>
                <td><code>${escapeHtml(rule.target_column)}</code></td>
                <td><strong>${escapeHtml(rule.source_value)}</strong></td>
                <td><strong>${escapeHtml(rule.target_value)}</strong></td>
                <td>${condition}</td>
                <td>${escapeHtml(rule.notes || '')}</td>
                <td>${escapeHtml(rule.created_by || 'system')}</td>
                <td>${createdAt}</td>
                <td>
                    <i class="fas fa-arrow-up edit-icon" title="${t('rules.move_up')}" onclick="moveRuleUp(${rule.id})"></i>
                    <i class="fas fa-arrow-down edit-icon" title="${t('rules.move_down')}" onclick="moveRuleDown(${rule.id})"></i>
                    <i class="fas fa-edit edit-icon" title="${t('rules.edit')}" onclick="editRule(${rule.id})"></i>
                    <i class="fas fa-copy edit-icon" title="${t('rules.clone')}" onclick="cloneRule(${rule.id})"></i>
                    <i class="fas fa-trash delete-icon" title="${t('delete')}" onclick="deleteRule(${rule.id})"></i>
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
            showError(t('rules.val.translation_required'));
            return;
        }
    } else {
        if (!data.target_column || data.target_value === null || data.target_value === undefined) {
            showError(t('rules.val.overwrite_required'));
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
                showSuccess(t('rules.add_success'));
                loadRules();
            } else {
                showError(t('rules.add_error') + ': ' + response.error);
            }
        },
        error: function(xhr) {
            const error = xhr.responseJSON ? xhr.responseJSON.error : xhr.responseText;
            showError(t('rules.add_error') + ': ' + error);
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
                $('#toggleEditConditionBtn').text(hasCondition ? t('rules.remove_condition') : t('rules.add_condition'));
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
                $('#toggleConditionBtn').text(hasCondition ? t('rules.remove_condition') : t('rules.add_condition'));
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
        showError(t('rules.val.target_required'));
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
                showSuccess(t('rules.update_success'));
                loadRules();
            } else {
                showError(t('rules.update_error') + ': ' + response.error);
            }
        },
        error: function(xhr) {
            const error = xhr.responseJSON ? xhr.responseJSON.error : xhr.responseText;
            showError(t('rules.update_error') + ': ' + error);
        }
    });
}

function deleteRule(id) {
    if (!confirm(t('rules.delete_confirm'))) {
        return;
    }
    
    $.ajax({
        url: `/rules/${id}/delete`,
        method: 'POST',
        success: function(response) {
            if (response.success) {
                showSuccess(t('rules.delete_success'));
                loadRules();
            } else {
                showError(t('rules.delete_error') + ': ' + response.error);
            }
        },
        error: function(xhr) {
            const error = xhr.responseJSON ? xhr.responseJSON.error : xhr.responseText;
            showError(t('rules.delete_error') + ': ' + error);
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
                showError(response.error || t('rules.move_error'));
            }
        },
        error: function(xhr) {
            const error = xhr.responseJSON ? xhr.responseJSON.error : xhr.responseText;
            showError(t('rules.move_error') + ': ' + error);
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
                showError(response.error || t('rules.move_error'));
            }
        },
        error: function(xhr) {
            const error = xhr.responseJSON ? xhr.responseJSON.error : xhr.responseText;
            showError(t('rules.move_error') + ': ' + error);
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
    alert(t('error_prefix') + message);
}
