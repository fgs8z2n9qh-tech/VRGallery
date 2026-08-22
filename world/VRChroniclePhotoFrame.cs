// VRChronicle — in-world photo frame
//
// Downloads one image from a public https URL and shows it on a quad, then
// refreshes on an interval so a newly published photo appears without a rebuild.
//
// Setup (Unity 2022.3.22f1, VRChat Worlds SDK 3.10.4, UdonSharp):
//   1. Drop this file in Assets\_Project\PhotoFrame\.
//   2. Make a Quad (or any MeshRenderer) sized 16:9, e.g. scale 2.88 x 1.62 x 1
//      — the same proportions the ProTV "Main Screen" uses in this world.
//   3. Give it a material using Unlit/Texture (Built-in RP — this project is NOT URP).
//   4. Add this component, drag the renderer into `targetRenderer`, and paste the
//      published image URL into `imageUrl` (must be https and end at a real image).
//   5. Optional: set `refreshSeconds` (0 = download once, never refresh).
//
// Two gotchas that bite everyone:
//   * The VRCImageDownloader instance MUST be kept in a field. If it is a local
//     variable it gets collected and the download silently never completes.
//   * Viewers must have "Allow Untrusted URLs" enabled unless your host is on
//     VRChat's trusted list — otherwise the frame stays blank for them. Show the
//     fallback texture so it does not look broken.

using UdonSharp;
using UnityEngine;
using VRC.SDK3.Image;
using VRC.SDK3.Components.Video;
using VRC.SDKBase;
using VRC.Udon.Common.Interfaces;

[UdonBehaviourSyncMode(BehaviourSyncMode.None)]
public class VRChroniclePhotoFrame : UdonSharpBehaviour
{
    [Tooltip("Public https URL of the published frame image (frame.jpg).")]
    public VRCUrl imageUrl = new VRCUrl("");

    [Tooltip("Renderer whose material gets the downloaded texture.")]
    public Renderer targetRenderer;

    [Tooltip("Shown while loading and if the download fails.")]
    public Texture2D fallbackTexture;

    [Tooltip("Seconds between refreshes. 0 downloads once and stops.")]
    public float refreshSeconds = 300f;

    // Held as a field on purpose — see the gotcha note above.
    private VRCImageDownloader _downloader;
    private IUdonEventReceiver _self;
    private MaterialPropertyBlock _block;
    private bool _downloading;

    void Start()
    {
        _self = (IUdonEventReceiver)this;
        _downloader = new VRCImageDownloader();
        _block = new MaterialPropertyBlock();

        if (fallbackTexture != null)
        {
            _Apply(fallbackTexture);
        }
        _Fetch();
    }

    public void _Fetch()
    {
        if (_downloading || targetRenderer == null) { return; }
        if (imageUrl == null || string.IsNullOrEmpty(imageUrl.Get())) { return; }

        _downloading = true;
        TextureInfo info = new TextureInfo();
        info.GenerateMipMaps = true;
        info.WrapModeU = TextureWrapMode.Clamp;
        info.WrapModeV = TextureWrapMode.Clamp;
        info.AnisoLevel = 4;
        _downloader.DownloadImage(imageUrl, targetRenderer.sharedMaterial, _self, info);
    }

    public override void OnImageLoadSuccess(IVRCImageDownload result)
    {
        _downloading = false;
        _Apply(result.Result);
        _Reschedule();
    }

    public override void OnImageLoadError(IVRCImageDownload result)
    {
        _downloading = false;
        Debug.LogWarning("[VRChronicle] frame download failed: " + result.ErrorMessage);
        if (fallbackTexture != null)
        {
            _Apply(fallbackTexture);
        }
        _Reschedule();
    }

    private void _Apply(Texture tex)
    {
        if (targetRenderer == null || tex == null) { return; }
        targetRenderer.GetPropertyBlock(_block);
        _block.SetTexture("_MainTex", tex);
        targetRenderer.SetPropertyBlock(_block);
    }

    private void _Reschedule()
    {
        if (refreshSeconds > 0f)
        {
            SendCustomEventDelayedSeconds(nameof(_Fetch), Mathf.Max(30f, refreshSeconds));
        }
    }
}
