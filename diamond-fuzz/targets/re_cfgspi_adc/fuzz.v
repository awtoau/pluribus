module fuzz(input wire sck,input wire cs_n,output wire miso);
  localparam [63:0] IDENT=64'h0200010913310785;
  reg [5:0] cnt;
  always @(posedge sck) if(cs_n) cnt<=0; else cnt<=cnt+1'b1;
  assign miso=IDENT[6'd63-cnt];
endmodule
