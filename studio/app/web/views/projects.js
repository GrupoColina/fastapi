// Tela de projetos: CRUD completo via /api/admin/projects.

import { api } from '/api.js';
import {
  checkboxField,
  confirmAction,
  empty,
  esc,
  field,
  fmtDateTime,
  loading,
  openModal,
  qs,
  readForm,
  showError,
  textareaField,
  toast,
} from '/ui.js';

function projectForm(project = {}) {
  const isEdit = Boolean(project.id);
  return `
    <form id="project-form">
      ${isEdit ? '' : field('Slug', 'slug', { value: project.slug || '', required: true, placeholder: 'meu-projeto' })}
      ${field('Nome', 'name', { value: project.name || '', required: true })}
      ${textareaField('Descrição', 'description', project.description || '', 3)}
      ${field('OpenAPI title', 'openapi_title', { value: project.openapi_title || '' })}
      ${field('OpenAPI version', 'openapi_version', { value: project.openapi_version || '1.0.0' })}
      ${checkboxField('Ativo', 'is_active', project.is_active !== false)}
      <div class="modal__actions"><button type="submit" class="btn btn--primary">${isEdit ? 'Salvar' : 'Criar projeto'}</button></div>
    </form>`;
}

function openProjectModal(project, onDone) {
  const isEdit = Boolean(project && project.id);
  openModal(isEdit ? 'Editar projeto' : 'Novo projeto', projectForm(project || {}), {
    onMount(body, close) {
      const form = qs('#project-form', body);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const values = readForm(form);
        try {
          if (isEdit) {
            const { slug, ...payload } = values;
            await api.updateProject(project.id, payload);
            toast('Projeto atualizado.', 'success');
          } else {
            await api.createProject(values);
            toast('Projeto criado.', 'success');
          }
          close();
          await onDone();
        } catch (err) {
          showError(err);
        }
      });
    },
  });
}

export async function renderProjects(view) {
  view.innerHTML = loading('carregando projetos…');
  const projects = await api.listProjects();

  view.innerHTML = `
    <section class="card">
      <div class="card__head">
        <h2>Projetos</h2>
        <button class="btn btn--primary" id="btn-new-project">Novo projeto</button>
      </div>
      ${
        projects.length
          ? `<table class="table">
              <thead><tr><th>Id</th><th>Slug</th><th>Nome</th><th>OpenAPI</th><th>Ativo</th><th>Criado</th><th></th></tr></thead>
              <tbody>
                ${projects
                  .map(
                    (project) => `
                  <tr>
                    <td>${esc(project.id)}</td>
                    <td><code>${esc(project.slug)}</code></td>
                    <td>${esc(project.name)}</td>
                    <td>${esc(project.openapi_title)} <span class="muted">${esc(project.openapi_version)}</span></td>
                    <td>${project.is_active ? '<span class="pill pill--ok">ativo</span>' : '<span class="pill">inativo</span>'}</td>
                    <td>${esc(fmtDateTime(project.created_at))}</td>
                    <td class="table__actions">
                      <button class="btn btn--sm" data-action="edit" data-id="${esc(project.id)}">Editar</button>
                      <button class="btn btn--sm btn--danger" data-action="delete" data-id="${esc(project.id)}">Remover</button>
                    </td>
                  </tr>`,
                  )
                  .join('')}
              </tbody>
            </table>`
          : empty('Nenhum projeto cadastrado.')
      }
    </section>`;

  const reload = () => renderProjects(view);
  qs('#btn-new-project', view).addEventListener('click', () => openProjectModal(null, reload));

  view.querySelectorAll('[data-action="edit"]').forEach((button) => {
    button.addEventListener('click', () => {
      const project = projects.find((item) => item.id === Number(button.dataset.id));
      openProjectModal(project, reload);
    });
  });

  view.querySelectorAll('[data-action="delete"]').forEach((button) => {
    button.addEventListener('click', async () => {
      const project = projects.find((item) => item.id === Number(button.dataset.id));
      if (!confirmAction(`Remover o projeto "${project.name}" (slug ${project.slug})?`)) return;
      try {
        await api.deleteProject(project.id);
        toast('Projeto removido.', 'success');
        await reload();
      } catch (err) {
        showError(err);
      }
    });
  });
}
