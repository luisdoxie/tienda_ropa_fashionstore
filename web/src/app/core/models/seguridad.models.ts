export interface Permiso {
  id: number;
  codigo: string;
  modulo: string;
  descripcion: string | null;
}

export interface Rol {
  id: number;
  nombre: string;
  descripcion: string | null;
  activo: boolean;
  permisos: Permiso[];
}

export interface RolCrear {
  nombre: string;
  descripcion?: string | null;
}

export type RolActualizar = Partial<RolCrear>;

export interface Usuario {
  id: number;
  nombre: string;
  apellido: string;
  email: string;
  telefono: string | null;
  activo: boolean;
  roles: string[];
}

export interface UsuarioYo extends Usuario {
  permisos: string[];
  /** null = superadministrador de la plataforma (no pertenece a una empresa). */
  empresa_id?: number | null;
  empresa_codigo?: string | null;
  empresa_nombre?: string | null;
}

export interface UsuarioCrear {
  nombre: string;
  apellido: string;
  email: string;
  telefono?: string | null;
  password: string;
}

export interface UsuarioActualizar {
  nombre?: string;
  apellido?: string;
  telefono?: string | null;
  activo?: boolean;
}

export interface TokenRespuesta {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface RecuperarRespuesta {
  detail: string;
  /** Solo viene informado cuando el backend corre en entorno local (sin servicio de correo real). */
  token_dev?: string | null;
}

export interface RegistroRequest {
  nombre: string;
  apellido: string;
  email: string;
  telefono?: string | null;
  password: string;
  ci_nit?: string | null;
}
