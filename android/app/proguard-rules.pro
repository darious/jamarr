# Stage 1 POC: no custom release shrinking rules yet.

# jUPnP uses reflection (annotations, XML binding). Keep it whole.
-keep class org.jupnp.** { *; }
-keepclassmembers class org.jupnp.** { *; }
-keep class org.slf4j.** { *; }
-dontwarn org.osgi.**
-dontwarn javax.annotation.**
-dontwarn org.jupnp.**
