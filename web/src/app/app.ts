import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { ToastModule } from 'primeng/toast';
import { AvisoPwaComponent } from './shared/aviso-pwa/aviso-pwa.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, ToastModule, AvisoPwaComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {}
