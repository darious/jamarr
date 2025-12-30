<script lang="ts">
  import QueueDrawer from "$components/QueueDrawer.svelte";
  import { clearQueue } from "$stores/player";
  import { goto } from "$app/navigation";

  const handleClose = () => goto("/");
  const handleClear = () => clearQueue(true);
</script>

<div class="min-h-screen bg-surface-900">
  <QueueDrawer visible={true} on:close={handleClose} on:clear={handleClear} />
</div>
